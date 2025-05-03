import streamlit as st
import os
import json
import re
import time
import random
from datetime import datetime, timedelta
from pathlib import Path
import logging
import google.generativeai as genai
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate
from langchain.schema import Document

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("EgyptianNewsRAG")

class RateLimiter:
    """Rate limiter to prevent exceeding Gemini API quotas"""
    def __init__(self, max_calls_per_minute=4):
        self.max_calls = max_calls_per_minute
        self.calls = []
        
    def wait_if_needed(self):
        """Wait if we've exceeded our rate limit"""
        now = time.time()
        # Remove calls older than 1 minute
        self.calls = [call_time for call_time in self.calls if now - call_time < 60]
        
        # If we've reached the limit, wait
        if len(self.calls) >= self.max_calls:
            oldest_call = min(self.calls)
            sleep_time = 60 - (now - oldest_call) + random.uniform(0.1, 1.0)
            logger.info(f"Rate limit reached. Waiting {sleep_time:.2f} seconds...")
            
            with st.status(f"API rate limit reached. Waiting {sleep_time:.1f} seconds..."):
                time.sleep(max(0, sleep_time))
        
        # Add this call to the list
        self.calls.append(time.time())

class EgyptianNewsRAG:
    def __init__(self, data_dir="egyptian_news_dataset", api_key=None):
        """Initialize the RAG system with the Egyptian news dataset"""
        self.data_dir = data_dir
        
        # Set up Google API key
        if api_key:
            os.environ["GOOGLE_API_KEY"] = api_key
            genai.configure(api_key=api_key)
        elif "GOOGLE_API_KEY" in os.environ:
            genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
        else:
            st.error("Please provide a Google API key in the sidebar.")
            return
        
        # Initialize rate limiter
        self.rate_limiter = RateLimiter(max_calls_per_minute=4)
        
        # Initialize embeddings model
        self.embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
        
        # Initialize LLM with lower temperature for more concise responses
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-1.5-pro",
            temperature=0.1,  # Lower temperature for more concise responses
            max_output_tokens=300,  # Limit output tokens
            convert_system_message_to_human=True
        )
        
        # Set up vector store directory
        self.db_directory = Path("egyptian_news_vectorstore")
        
        # Initialize text splitter for chunking - smaller chunks for better retrieval
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=800,  # Smaller chunks to reduce token usage
            chunk_overlap=100,  # Reduced overlap
            length_function=len,
        )
        
        # Custom prompt template for question answering - optimized for conciseness
        self.qa_template = """
        أنت خبير في الأخبار المصرية. أجب على السؤال فقط بناءً على السياق التالي.
        You are an expert on Egyptian news. Answer the question based ONLY on the following context.
        
        Context:
        {context}
        
        Question: {question}
        
        Instructions:
        1. If the answer isn't in the context, say "I don't have information about that in my current Egyptian news database."
        2. Keep your answer under 3 sentences.
        3. Answer in the same language as the question (Arabic or English).
        4. Today is April 22, 2025.
        
        Answer:
        """
        
        self.qa_prompt = PromptTemplate(
            template=self.qa_template,
            input_variables=["context", "question"]
        )
        
        # Fallback prompt for when no relevant information is found
        self.fallback_prompt = """
        أنت مساعد ذكي متخصص في الأخبار المصرية. المستخدم يسأل عن:
        You are an intelligent assistant specialized in Egyptian news. The user is asking about:
        
        Question: {question}
        
        Instructions:
        1. Provide a helpful response based on your general knowledge about Egypt and current affairs.
        2. Answer in the same language as the question (Arabic or English).
        3. Keep your answer concise and informative.
        4. Today is April 22, 2025.
        
        Answer:
        """
        
        # Initialize vector store and QA chain
        self.vectorstore = None
        self.qa_chain = None
        self.retriever = None
        
        # Cache for query enhancement to reduce API calls
        self.query_cache = {}
        
        # Separate caches for Arabic and English queries
        self.arabic_query_cache = {}
        self.english_query_cache = {}

    def is_arabic(self, text):
        """Check if the text contains Arabic characters"""
        arabic_pattern = re.compile(r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]+')
        return bool(arabic_pattern.search(text))

    def standardize_date(self, date_text):
        """Convert various date formats to a standard format"""
        if not date_text or date_text == "No date found":
            return date_text
            
        try:
            # Common Arabic month names
            arabic_months = {
                'يناير': 'January', 'فبراير': 'February', 'مارس': 'March',
                'أبريل': 'April', 'مايو': 'May', 'يونيو': 'June',
                'يوليو': 'July', 'أغسطس': 'August', 'سبتمبر': 'September',
                'أكتوبر': 'October', 'نوفمبر': 'November', 'ديسمبر': 'December'
            }
            
            # Try to standardize common Arabic date formats
            for ar_month, en_month in arabic_months.items():
                if ar_month in date_text:
                    date_text = date_text.replace(ar_month, en_month)
            
            return date_text
        except:
            return date_text

    def load_news_data(self):
        """Load all news data from JSON files"""
        logger.info("Loading Egyptian news data...")
        all_articles = []
        
        # Try to load the combined JSON file first
        combined_files = list(Path(self.data_dir).glob("all_egyptian_news_*.json"))
        if combined_files:
            latest_file = max(combined_files, key=lambda x: x.stat().st_mtime)
            with open(latest_file, 'r', encoding='utf-8') as f:
                all_articles = json.load(f)
            return all_articles
        
        # If combined file doesn't exist, try individual website files
        website_files = list(Path(self.data_dir).glob("*_articles_*.json"))
        for file_path in website_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    articles = json.load(f)
                    all_articles.extend(articles)
            except Exception as e:
                logger.error(f"Error loading {file_path}: {e}")
        
        return all_articles

    def create_documents(self, articles):
        """Convert news articles to Document objects with proper date handling"""
        documents = []
        
        for article in articles:
            content = article.get('content', '')
            if not content or content == "No content found":
                continue
            
            # Ensure date is properly formatted
            date = article.get('date', 'No date found')
            if date == "No date found" and article.get('original_date'):
                date = article.get('original_date')
            
            # Standardize date format
            date = self.standardize_date(date)
            
            # Create metadata with properly formatted date
            metadata = {
                'title': article.get('title', 'No title'),
                'source': article.get('source', 'Unknown'),
                'date': date,
                'url': article.get('url', '')
            }
            
            doc = Document(page_content=content, metadata=metadata)
            documents.append(doc)
        
        return documents

    def chunk_documents(self, documents):
        """Split documents into smaller chunks for better retrieval and lower token usage"""
        chunks = self.text_splitter.split_documents(documents)
        return chunks

    def create_vector_store(self, chunks):
        """Create or load vector store from document chunks"""
        if self.db_directory.exists():
            try:
                vectorstore = Chroma(
                    persist_directory=str(self.db_directory),
                    embedding_function=self.embeddings
                )
                return vectorstore
            except Exception as e:
                logger.error(f"Error loading vector store: {e}")
        
        # Create new vector store
        vectorstore = Chroma.from_documents(
            documents=chunks,
            embedding=self.embeddings,
            persist_directory=str(self.db_directory)
        )
        vectorstore.persist()
        return vectorstore

    def setup_retriever(self, vectorstore):
        """Set up the retriever with more documents for better coverage"""
        # Retrieve more documents for better coverage
        retriever = vectorstore.as_retriever(
            search_type="similarity",
            search_kwargs={"k": 10}  # Increased from 5 to 10
        )
        
        return retriever

    def setup_qa_chain(self, retriever):
        """Set up the QA chain with the retriever"""
        try:
            self.rate_limiter.wait_if_needed()
            
            qa_chain = RetrievalQA.from_chain_type(
                llm=self.llm,
                chain_type="stuff",
                retriever=retriever,
                return_source_documents=True,
                chain_type_kwargs={"prompt": self.qa_prompt}
            )
            
            return qa_chain
        except Exception as e:
            logger.error(f"Error setting up QA chain: {e}")
            raise

    def initialize_system(self):
        """Initialize the complete RAG system with progress indicators"""
        with st.spinner("Loading data..."):
            articles = self.load_news_data()
            documents = self.create_documents(articles)
            chunks = self.chunk_documents(documents)
            
        with st.spinner("Building database..."):
            self.vectorstore = self.create_vector_store(chunks)
            self.retriever = self.setup_retriever(self.vectorstore)
            self.qa_chain = self.setup_qa_chain(self.retriever)
            
        st.success(f"System ready with {len(chunks)} chunks")
        return True

    def answer_question(self, query):
        """Answer a question using the RAG system with fallback to Gemini"""
        if not self.qa_chain:
            return "System not initialized."
        
        try:
            # Check if query is in Arabic
            is_arabic_query = self.is_arabic(query)
            
            # Use appropriate cache based on language
            cache_dict = self.arabic_query_cache if is_arabic_query else self.english_query_cache
            
            # Check cache first
            cache_key = query.strip().lower()
            if cache_key in cache_dict:
                return cache_dict[cache_key]
            
            # Apply rate limiting
            self.rate_limiter.wait_if_needed()
            
            # Get answer from QA chain
            result = self.qa_chain({"query": query})
            
            answer = result["result"]
            
            # Check if the answer indicates no information was found
            no_info_indicators = [
                "I don't have information",
                "لا توجد معلومات",
                "لم أجد معلومات",
                "لا أملك معلومات"
            ]
            
            if any(indicator in answer for indicator in no_info_indicators):
                # If no information found, use Gemini's general knowledge
                self.rate_limiter.wait_if_needed()
                
                # Format fallback prompt with query
                fallback_prompt = self.fallback_prompt.format(question=query)
                
                # Get response from Gemini
                response = self.llm.invoke(fallback_prompt)
                answer = response.content
            
            # Cache the result in the appropriate language cache
            cache_dict[cache_key] = answer
            
            return answer
        
        except Exception as e:
            logger.error(f"Error answering question: {e}")
            if "429" in str(e):
                return "Rate limit reached. Please try again in a minute."
            else:
                return f"Error: {str(e)}"

# Streamlit UI implementation
def main():
    st.set_page_config(page_title="Egyptian News Q&A", layout="wide")
    
    st.title("Egyptian News Q&A")
    st.markdown("Ask questions about Egyptian news in Arabic or English")
    
    # Initialize session state
    if "messages" not in st.session_state:
        st.session_state.messages = []
    
    if "rag_system" not in st.session_state:
        st.session_state.rag_system = None
        st.session_state.system_initialized = False
    
    # Sidebar for configuration
    with st.sidebar:
        st.header("Configuration")
        api_key = st.text_input("Google API Key", type="password")
        data_dir = st.text_input("Data Directory", value="egyptian_news_dataset")
        
        if st.button("Initialize System"):
            try:
                st.session_state.rag_system = EgyptianNewsRAG(
                    data_dir=data_dir,
                    api_key=api_key
                )
                st.session_state.system_initialized = st.session_state.rag_system.initialize_system()
            except Exception as e:
                st.error(f"Error initializing system: {str(e)}")
        
        st.divider()
        
        # API Usage Information
        st.subheader("API Usage Information")
        st.info("""
        Free tier Gemini API limits:
        - ~5 requests per minute
        - Limited daily requests
        
        This app is optimized to:
        - Keep responses concise
        - Cache previous queries
        - Use Gemini for missing information
        """)
        
        # Example questions
        st.subheader("Example Questions")
        examples = [
            "ما هي أحدث التطورات في العلاقات المصرية السعودية؟",
            "What are the latest economic indicators in Egypt?",
            "من هو وزير الخارجية المصري الحالي؟",
            "ما هي آخر أخبار الأهلي المصري؟",
            "What is happening in Gaza according to Egyptian media?"
        ]
        
        for question in examples:
            if st.button(question):
                st.session_state.messages.append({"role": "user", "content": question})
                if st.session_state.system_initialized:
                    answer = st.session_state.rag_system.answer_question(question)
                    st.session_state.messages.append({"role": "assistant", "content": answer})
                else:
                    st.error("Please initialize the system first")
    
    # Display chat history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
    
    # Chat input
    if prompt := st.chat_input("Ask about Egyptian news..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        with st.chat_message("user"):
            st.markdown(prompt)
        
        if st.session_state.system_initialized:
            with st.chat_message("assistant"):
                with st.spinner("Thinking..."):
                    answer = st.session_state.rag_system.answer_question(prompt)
                st.markdown(answer)
                
                st.session_state.messages.append({"role": "assistant", "content": answer})
        else:
            st.error("Please initialize the system first")
    
    # Clear conversation button
    if st.session_state.messages and st.button("Clear Conversation"):
        st.session_state.messages = []
        st.rerun()

if __name__ == "__main__":
    main()
