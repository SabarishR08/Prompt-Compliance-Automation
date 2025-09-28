# **🤖 Prompt Compliance Automation**

Prompt Compliance Automation is a **middleware solution** designed to help organizations securely leverage Large Language Models (LLMs) while rigorously protecting sensitive and confidential data.

It automatically analyzes and moderates prompts to detect **toxic content**, **sensitive keywords**, and **Personally Identifiable Information (PII)**, ensuring that unsafe content is either redacted or blocked. This allows users to safely continue using AI tools without risking **data leakage** or **regulatory non-compliance**.

## **🚀 Hackathon Project – PEC Techathon 3.0 powered by Cognizant**

Team: Prompt Monks  
Sabarish R (lead)

## **📌 Problem Statement**

Organizations increasingly rely on LLMs for tasks such as debugging, documentation, and brainstorming. Employees may unknowingly share sensitive data (PII, API keys, source code, internal assets) with external AI tools, creating risks such as:

1. **Data Leakage** and **Asset Loss**.  
2. **Regulatory Non-compliance** (e.g., GDPR, ISO).

**Prompt Compliance Automation** solves this by acting as a secure gateway, ensuring all prompts are safe, compliant, and redacted before reaching the LLM.

## **🎯 Goals**

| Goal | Description |
| :---- | :---- |
| **Real-time Detection** | Detect blocked/flagged keywords and entities in real time. |
| **PII Management** | Identify and redact PII while preserving the surrounding context. |
| **Toxicity Analysis** | Detect toxic or unsafe content using pre-trained ML models. |
| **Configurability** | Provide configurable compliance rules and moderation modes. |
| **Audit Trails** | Maintain structured logs of all actions for audit and monitoring purposes. |

## **🛠️ Solution Overview**

Prompt Compliance Automation sits between the user and the external LLM, processing and moderating the input based on defined compliance rules.

### **Workflow**

1. **Prompt** → **API (FastAPI)**  
2. **API** → **Analyzer**  
3. **Analyzer** performs checks (Keyword, PII, Toxicity).  
4. Prompt is **Redacted & Classified** (Safe, Flagged, or Blocked).  
5. Action is **Logged (SQLite)**.  
6. If **Safe**, the prompt is forwarded to **Gemini/Local LLM** for a response.  
7. If **Flagged/Blocked**, the user receives an alert/rejection.  
8. All activity is visible on the **Dashboard (HTML/JS)**.

### **✅ Key Features**

* Real-time prompt analysis.  
* Keyword filtering (flagged & blocked terms).  
* PII detection & redaction (phone numbers, ATM PINs, credit cards, etc.).  
* Toxicity analysis using ML thresholds via Detoxify.  
* Audio alerts for flagged/blocked prompts.  
* SQLite database for audit logs.  
* Supports multiple moderation modes: **Default / Custom / Hybrid**.  
* Supports optional **local LLMs** to generate responses for safe prompts without sending confidential data to external APIs.

### **📊 Metrics Impact**

* Boosts toxic/sensitive content detection rates.  
* Reduces the need for manual prompt moderation efforts.  
* Ensures PII redaction with traceable, time-stamped logs.  
* Provides configurable, centralized compliance rules across the organization.

## **🖥️ Architecture & Tech Stack**

The solution is built as a lightweight, scalable microservice ready for deployment.

### **⚙️ Tech Stack**

| Component | Technology | Role |
| :---- | :---- | :---- |
| **Backend API** | Python, FastAPI | High-performance API serving the middleware logic. |
| **Frontend** | HTML, CSS, JavaScript | Simple dashboard for prompt testing and log visualization. |
| **NLP/ML** | spaCy, Presidio, Detoxify | Core analysis, PII detection, and content moderation. |
| **Database** | SQLite | Local, reliable storage for compliance and audit logs. |

## **⚙️ Installation & Setup**

Follow these steps to get the Prompt Compliance Automation service running locally.

### **1️⃣ Clone the repository**

git clone \[https://github.com/SabarishR08/Prompt-Compliance-Automation.git\](https://github.com/SabarishR08/Prompt-Compliance-Automation.git)  
cd Prompt-Compliance-Automation

### **2️⃣ Create virtual environment & install dependencies**

\# Create and activate environment  
python \-m venv venv  
source venv/bin/activate   \# On Linux/Mac  
venv\\Scripts\\activate      \# On Windows

\# Install required packages  
pip install \-r requirements.txt

### **3️⃣ Setup environment variables (.env)**

Create a file named .env in the project root to configure the Gemini API key and paths for the audio alerts:

GEMINI\_API\_KEY=your\_google\_api\_key  
ALERT\_PII\_PATH=./sound\_alerts/PII\_Alert.mp3  
ALERT\_POLICY\_PATH=./sound\_alerts/Policy-Violation\_Alert.mp3

### **4️⃣ Run the application**

uvicorn app:app \--reload \--port 8000

Visit: http://127.0.0.1:8000 to access the frontend dashboard.

## **📂 Project Structure**

Prompt-Compliance-Automation/  
│   .env  
│   .gitignore  
│   app.py                  \# Main FastAPI logic  
│   clear\_db.py             \# Script to clear the SQLite DB  
│   index.html              \# Frontend dashboard  
│   logs.db                 \# SQLite database  
│   README.md  
│   requirements.txt  
│   settings.json           \# Configurable policy rules  
├───sound\_alerts/  
│       PII\_Alert.mp3  
│       Policy-Violation\_Alert.mp3  
└───\_\_pycache\_\_/

## **🔑 API Endpoints**

| Method | Endpoint | Description |
| :---- | :---- | :---- |
| POST | /check\_prompt | Analyzes prompt, returns compliance status, and Gemini/local LLM response if safe. |
| GET | /get\_logs | Fetch all stored logs. |
| POST | /clear\_logs | Clear logs from DB. |
| POST | /update\_mode | Update compliance mode (default/custom/hybrid). |
| GET | /get\_settings | Fetch current policy settings. |

## **📊 Sample Workflow**

1. **User submits a prompt.**  
2. API checks: Blocked keywords, PII entities (via **Presidio**), and Toxicity scores (via **Detoxify**).  
3. Prompt is classified as:  
   * ✅ **Safe** → Forward to Gemini or local LLM, log response.  
   * ⚠️ **Flagged** → Redacted / Warning raised.  
   * ⛔ **Blocked** → Rejected with alert sound.  
4. Logs stored in **SQLite** for audits.

**Future Enhancement:** Blocked/unsafe prompts can be suggested a safe rephrased prompt using a trained local middleware LLM before sending to external LLM servers (e.g., OpenAI).

## **📚 Real-World Relevance**

### **Use Case Scenario**

In organizations, employees often use AI tools/LLMs to debug errors or generate code. They may inadvertently paste entire source code, API keys, or internal data into the AI tool.

* **Problem:** Data leakage, asset loss, regulatory violations.  
* **Solution:** Our prototype acts as a middleware service. It analyzes prompts before forwarding them. Unsafe or confidential content is either blocked, redacted, or flagged. Employees can safely continue using LLMs without risking data breaches.

### **Industry Impact**

* **Samsung Data Leak (2023):** Engineers leaked source code into ChatGPT.  
* **Apple & Amazon Restrictions:** Limited employee usage of generative AI tools.  
* **Case Study:** A global IT company with 5,000+ developers found \~22% of employees pasted source code or API keys into external AI tools. Potential exposure of millions of lines of code could result in **$4.2M estimated losses**.

Our system could prevent such risks with proactive compliance filtering.

## **🔮 Future Scope**

* Multi-language & enterprise compliance support.  
* Dockerized microservice deployment.  
* Role-Based Access Control (RBAC).  
* MLOps monitoring dashboards.  
* Cloud scaling with AWS / GCP.  
* Middleware LLM for safe rephrasing: Suggest alternate safe prompts for blocked/unsafe inputs.  
* Expand local LLM integration for response generation without exposing confidential data.

## **👨‍💻 Contributors**

* **Sabarish R (Lead):** Backend, ML Integration, DB, Documentation
* **Team :** Frontend, Research

## **📜 License**

This project is licensed under the **MIT License**.
