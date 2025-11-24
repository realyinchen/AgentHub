# 🧠 AI Agent Hub

一个使用 FastAPI（后端）和 Streamlit（前端）构建的模块化 Agent 集合框架。

这是 [learn_langchain_langgraph](https://github.com/realyinchen/learn_langchain_langgraph) 中 Agent 的 GUI 版本。

灵感来源：[agent-service-toolkit](https://github.com/JoshuaC215/agent-service-toolkit)

关注我的微信公众号获取最新推送

![wechat_qrcode](https://github.com/realyinchen/RAG/blob/main/imgs/wechat_qrcode.jpg)

### 🚀 项目特点

✅ FastAPI 后端 — 稳健的 RESTful API 层，用于 Agent 调度与异步任务管理。  
✅ Streamlit 前端 — 交互式网页界面，用于实验 Agent 与可视化推理图谱。  
✅ LangChain/LangGraph 集成 — 轻松构建设计并连接多 Agent 推理工作流，并进行可视化。  
✅ 流式与事件驱动 — 实时 token 流输出和 Agent 执行事件的可视化。

### 🧩 适用于：

想要更高效地展示 LangChain 与 LangGraph 学习成果的同学。 

### 快速启动项目

1. 安装 [VS Code](https://code.visualstudio.com/Download) 与 [miniconda](https://docs.anaconda.com/miniconda/miniconda-install/)

2. 创建虚拟环境  
    ``` bash
    $ conda create -n agenthub python=3.12
    ```

3. 激活虚拟环境  
    ``` bash
    $ conda activate agenthub
    ```

4. 进入项目根目录  AgentHub  
   将项目根目录下的环境变量配置文件重命名，并根据实际情况，填入你的配置信息  
    ``` bash
    $ mv .example.env .env
    ```

5. 安装依赖包
    ``` bash
    $ pip install -r requirements.txt
    ```

6. 运行项目  
    启动后端  
    ``` bash
    $ python src/run_backend.py 
    ```
    启动前端  
    ``` bash
    $ streamlit run src/streamlit_app.py
    ```