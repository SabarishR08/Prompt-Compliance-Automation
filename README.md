# **🚀 Prompt Compliance Automation**

**An automated compliance layer for Generative AI prompts, designed to detect and mitigate risks such as PII leaks, toxic content, and unsafe language before execution.**

## **📌 Overview**

With the rapid adoption of Generative AI, enterprises face growing risks:

* ⚠️ **Sensitive Data Exposure** — Prompts may unintentionally leak personal or confidential information.  
* ⚠️ **Toxic / Harmful Inputs** — Unsafe prompts can lead to biased or offensive outputs.  
* ⚠️ **Compliance Gaps** — A lack of audit trails and governance in AI adoption.

**Prompt Compliance Automation** provides a **lightweight, plug-and-play compliance layer** that:

* ✅ Detects **PII, toxic language, and flagged keywords**.  
* ✅ **Redacts or blocks** unsafe prompts in real-time.  
* ✅ Maintains **audit logs** for compliance and governance.  
* ✅ Supports multiple modes — *Block, Redact, Monitor*.

## **🏗️ Features**

* 🔍 **Rule-based checks** (keywords & regex)  
* 🧠 **PII detection** using [Microsoft Presidio](https://microsoft.github.io/presidio/)  
* 🤖 **Toxicity & hate speech detection** via [Detoxify](https://github.com/unitaryai/detoxify)  
* 📊 **Audit logging** with SQLite  
* 🎛️ **Customizable settings** via settings.json  
* 🌐 **REST API** built with FastAPI with CORS enabled  
* 🖥️ **Frontend-ready** with a prototype UI in index.html

## **⚙️ Tech Stack**

* **Backend:** Python, FastAPI  
* **ML/NLP:** spaCy, Presidio Analyzer, Detoxify (PyTorch)  
* **Database:** SQLite (logs.db)  
* **Frontend (prototype):** HTML, CSS (Tailwind-like utility), JavaScript, Chart.js

## **📂 Project Structure**

📦 Prompt-Compliance-Automation  
├── app.py              \# FastAPI backend with ML/NLP checks  
├── index.html          \# Prototype frontend UI  
├── requirements.txt    \# Python dependencies  
├── settings.json       \# Configurable thresholds & rules  
├── logs.db             \# SQLite database for audit logs  
└── pycache/            \# Compiled cache (ignored)

## **🚀 Getting Started**

### **🔧 Installation**

1. **Clone the repository**  
   git clone \[https://github.com/SabarishR08/Prompt-Compliance-Automation.git\](https://github.com/SabarishR08/Prompt-Compliance-Automation.git)  
   cd Prompt-Compliance-Automation

2. **Create a virtual environment (recommended)**  
   python \-m venv venv  
   source venv/bin/activate  \# On Linux/Mac  
   venv\\Scripts\\activate     \# On Windows

3. **Install dependencies**  
   pip install \-r requirements.txt

4. **Run the server**  
   uvicorn app:app \--reload

Your backend will run on http://127.0.0.1:8000.

5. Open the frontend  
   Simply open the index.html file in your browser to view the UI. (Make sure the backend is running for full functionality).

## **📡 API Endpoints**

| Endpoint | Method | Description |
| :---- | :---- | :---- |
| /check\_prompt | POST | Analyze a prompt and return compliance results. |
| /get\_logs | GET | Fetch audit logs from the database. |
| /update\_mode | POST | Switch compliance mode (Block / Redact / Monitor). |
| /get\_settings | GET | Retrieve the current configuration. |

## **📊 Architecture**

flowchart TD  
    A\[User Prompt\] \--\> B\[FastAPI Backend\]  
    B \--\> C\[Analyzer Engine\]  
    C \--\>|Keyword Checks| D\[Rule Engine\]  
    C \--\>|PII Detection| E\[Presidio\]  
    C \--\>|Toxicity Detection| F\[Detoxify\]  
    D & E & F \--\> G\[Decision Engine\]  
    G \--\>|Safe| H\[Forward to LLM/API\]  
    G \--\>|Flag/Block| I\[Audit Log \+ Dashboard\]

## **🖥️ Demo Screenshots**


* ✅ Prompt input UI  
* ✅ Compliance results with redacted text  
* ✅ Audit log dashboard

## **📌 Roadmap**

* Add multi-language support.  
* Integrate with enterprise databases (Postgres, MySQL).  
* Build a React dashboard for real-time monitoring.  
* Implement CI/CD and Docker deployment for easy scaling.

## **👨‍💻 Author**

**Sabarish R**

* B.Tech CSBS @ Panimalar Engineering College (2028)  
* **LinkedIn:** [Sabarish R | LinkedIn](https://www.linkedin.com/in/sabarishr08/)  
* **Email:** sabarish.edu2024@gmail.com

## **📜 License**

This project is licensed under the MIT License.

## **🙌 Acknowledgements**

* **PEC Techathon 3.0** for providing the hackathon use case.  
