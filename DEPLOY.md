# NeNe 番茄钟部署手册

> 本文档描述如何在 GitHub 托管代码、在 Render 托管后端、在 Netlify 托管前端，构建完整的 NeNe 番茄钟生产部署。所有指令均以 `main` 分支为例，可根据自身情况调整。

## 架构与目录

- **源代码**：GitHub 仓库 `nene-pomodoro`
- **后端**：`backend/` 目录，Flask + Gunicorn，在 Render Web Service 上运行
- **前端**：`frontend/` 目录，原生 HTML + JS，部署到 Netlify 静态站点
- **数据库**：默认 SQLite，仅适合临时环境；生产建议迁移到 Render PostgreSQL

```text
nene-pomodoro/
├── backend/
│   ├── app.py
│   ├── config.py
│   ├── extensions.py
│   ├── models.py
│   ├── routes.py
│   ├── Procfile
│   └── requirements.txt
├── frontend/
│   ├── app.js
│   └── index.html
└── DEPLOY.md
```

## 部署流程概览

| 步骤 | 平台 | 操作要点 |
| --- | --- | --- |
| Step 0 | 本地/GitHub | 准备仓库、提交代码 |
| Step 1 | Render | 创建 Web Service，指向 `backend/`，配置启动命令 |
| Step 2 | GitHub | 将 `frontend/app.js` 中的 `PROD_API_URL` 更新为 Render URL |
| Step 3 | Netlify | 连接仓库，指定 `frontend` 目录部署静态页面 |
| Step 4 | 运营 | 校验两个 URL 联通、设置自动部署、监控日志 |

---

## Step 0：准备 GitHub 仓库

1. **基本要求**
   - 安装 Git，并保证可以访问 GitHub。
   - 拥有 GitHub、Render、Netlify 账号。

2. **创建仓库**
   - 在 GitHub 上创建 `nene-pomodoro` (Public)。
   - 本地执行：

     ```bash
     git init
     git add .
     git commit -m "Initial commit"
     git branch -M main
     git remote add origin https://github.com/YOUR_USERNAME/nene-pomodoro.git
     git push -u origin main
     ```

   - 如需网页上传，请先在仓库中创建 `backend/.keep`、`frontend/.keep` 目录，再分别上传对应文件，防止结构错乱。

---

## Step 1：部署后端到 Render

1. 登录 [Render Dashboard](https://dashboard.render.com/)，点击 **New ➜ Web Service**。
2. 选择 **Build and deploy from a Git repository**，授权并选择 `nene-pomodoro`。
3. 配置：
   - **Name**：例如 `nene-backend`
   - **Region**：选择离主要用户最近的区域 (如 Singapore)
   - **Branch**：`main`
   - **Root Directory**：`backend`
   - **Runtime**：Python 3
   - **Build Command**：`pip install -r requirements.txt`
   - **Start Command**：`gunicorn app:app`
   - **Instance Type**：Free
4. 环境变量（可选但推荐）：
   - `PYTHON_VERSION=3.9.0`
   - 若使用云数据库：`DATABASE_URL=<Render PostgreSQL Internal URL>`
5. 点击 **Create Web Service**。初次部署结束后会拿到固定 URL，例如 `https://nene-pomodoro.onrender.com`。
6. 验证：
   - Render Logs 中无报错
   - 浏览器访问 `<render-url>/health` 或根路径得到 200 返回
   - 记下该 URL，供前端调用

### 数据持久化选项

- Render 免费实例的本地文件系统会在重启时重置，默认 SQLite 数据会消失。
- 需要持久化时在 Render 创建 PostgreSQL：
  1. **New ➜ PostgreSQL**，完成创建。
  2. 复制 **Internal Database URL**，在 Web Service 中设置 `DATABASE_URL`。
  3. 在 `backend/models.py` / `config.py` 中已经读取该变量，无需额外修改。
  4. 如需外部管理数据，可使用 External Database URL 配合 DBeaver、TablePlus 等工具连接。

### 常用维护操作

- **手动重新部署**：在 Service 页面点击 *Manual Deploy ➜ Clear build cache & deploy*。
- **回滚版本**：在 *Events* 中找到目标部署记录，点击 *Rollback*。
- **日志查看**：*Logs* 页签或 `render logs nene-backend` CLI。

---

## Step 2：配置前端 API 地址

1. 在 `frontend/app.js` 中查找：

   ```javascript
   const PROD_API_URL = 'https://YOUR-RENDER-APP-NAME.onrender.com';
   ```

2. 将其替换为上一节获取的 Render URL。
3. 将修改提交到 `main`：

   ```bash
   git add frontend/app.js
   git commit -m "chore: point frontend to render backend"
   git push origin main
   ```

4. 若不使用命令行，可在 GitHub 网页端直接编辑该文件并 Commit。

---

## Step 3：部署前端到 Netlify

1. 登录 [Netlify](https://app.netlify.com/)，点击 **Add new site ➜ Import an existing project**。
2. 选择 **GitHub**，授权并选择 `nene-pomodoro`。
3. 构建设置：
   - **Base directory**：`frontend`
   - **Build command**：留空（纯静态文件）
   - **Publish directory**：`frontend` （或留空让 Netlify 自动解析）
4. 点击 **Deploy site**，首个部署完成后会获得 URL，例如 `https://nene-pomodoro.netlify.app`。
5. 在 **Domain settings** 中可自定义子域名。
6. 确认站点能够正常访问，并能向 Render 后端发起请求（浏览器 Network 或控制台显示 200）。

### 自动部署 & 环境变量

- 默认开启 **Automatic deploys**：当 `main` 有新提交时，Netlify 与 Render 会各自重新部署。
- 若需要在前端注入配置，可在 **Site settings ➜ Environment variables** 添加键值，并在 JS 中通过 `process.env` 读取（需使用构建工具时才有意义，此项目为纯静态无需设置）。

---

## Step 4：发布与日常运维

1. **全链路验证**
   - 更新代码后等待 Render、Netlify 部署完成。
   - 在浏览器访问 Netlify URL，打开开发者工具确认 API 请求指向 Render 并返回 200。
   - 如需要后端管理界面，可访问 `<render-url>/admin`。

2. **通知渠道**
   - Render 与 Netlify 都支持通过 Email/Webhook/Slack 通知部署状态，可在各自 Settings 中开启。

3. **备份策略**
   - 使用 PostgreSQL 时，可在 Render 数据库设置里开启自动备份。
   - 若仍使用 SQLite，请手动下载 `instance/nene.db` 或改用云数据库。

---

## 故障排查

| 症状 | 可能原因 | 解决方式 |
| --- | --- | --- |
| Netlify 加载但 API 504/错误 | Render 免费实例休眠或 Start Command 错误 | 等待实例唤醒（约 50s），或在 Render Logs 中检查错误并重新部署 |
| Render 构建失败 | `Root Directory` 未设置为 `backend` 或 pip 报错 | 校正目录；手动执行 `pip install -r requirements.txt` 验证依赖 |
| GitHub 上传文件后结构混乱 | 直接拖拽导致目录扁平化 | 使用命令行或先创建文件夹再上传 |
| 管理后台暴露 | `/admin` 默认无鉴权 | 建议后续加入 Basic Auth 或第三方登录 |
| 数据丢失 | 仍在使用 SQLite | 切换到 Render PostgreSQL，并迁移数据 |

---

## 附录

- **Render Service URL**：`https://nene-pomodoro.onrender.com`
- **Netlify Site URL**：`https://nene-pomodoro.netlify.app`
- **GitHub 仓库**：`https://github.com/2584034162/nene-pomodoro`

保持 `main` 分支始终与生产一致，可在 GitHub 添加保护策略，确保每次合并都经过检查。至此，NeNe 番茄钟的端到端部署即告完成。
