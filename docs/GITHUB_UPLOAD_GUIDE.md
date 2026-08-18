# 两个项目上传GitHub教程（Windows PowerShell）

## 一、先理解当前目录

两个项目应当是两个独立仓库，不要把智维手册作为售后智办的子目录一起提交：

```text
C:\Users\ASUS\Documents\ChatGPT\agent_project                  售后智办仓库
C:\Users\ASUS\Documents\ChatGPT\agent_project\abc\shopkeer_brain 智维手册仓库
```

售后智办根目录的`.gitignore`已经忽略整个`abc/`；智维手册有自己的`.gitignore`。因此二者可以分别`git add`、分别上传。

## 二、在GitHub网页创建两个空仓库

登录GitHub后，右上角`+` → `New repository`，依次创建：

1. `servicepilot-agent`（售后智办）
2. `manual-rag-assistant`（智维手册）

建议选择`Public`，方便简历面试官访问。创建时不要勾选“Add a README file”“Add .gitignore”或License，因为本地已经存在这些文件。创建后保留网页给出的HTTPS地址。

## 三、上传售后智办

```powershell
cd C:\Users\ASUS\Documents\ChatGPT\agent_project

# 首次提交前验收
powershell -ExecutionPolicy Bypass -File scripts\verify_support.ps1
git status --ignored
git check-ignore .env

# 当前目录已初始化Git，只需建立首个提交
git branch -M main
git add .
git status
git commit -m "feat: build auditable after-sales agent workflow"

# 把<你的GitHub用户名>替换成自己的用户名
git remote add origin https://github.com/<你的GitHub用户名>/servicepilot-agent.git
git push -u origin main
```

如果提示`remote origin already exists`，先查看：

```powershell
git remote -v
```

地址错误时再执行：

```powershell
git remote set-url origin https://github.com/<你的GitHub用户名>/servicepilot-agent.git
```

## 四、上传智维手册

```powershell
cd C:\Users\ASUS\Documents\ChatGPT\agent_project\abc\shopkeer_brain

# 不调用API的离线验收
powershell -ExecutionPolicy Bypass -File .\verify_project.ps1
git status --ignored
git check-ignore knowledge/.env

# 只有第一次需要初始化
git init -b main
git add .
git status
git commit -m "feat: build multimodal manual RAG assistant"
git remote add origin https://github.com/<你的GitHub用户名>/manual-rag-assistant.git
git push -u origin main
```

`evaluation/work/`、官方PDF、本地模型、`knowledge/.env`和数据库文件会被忽略。GitHub中应当保留数据集说明、入库清单、逐题实验结果和截图，而不是提交大体积原始文件。

## 五、输入密码时怎么办

GitHub已不支持用账号密码执行HTTPS Git推送。Windows通常会弹出Git Credential Manager浏览器窗口，点击授权即可。如果终端要求Password，应使用Personal Access Token，不要输入GitHub登录密码，更不要把Token写进`.env`或代码。

## 六、上传前的密钥检查

两个仓库都执行以下检查：

```powershell
git status --ignored
git diff --cached --name-only
git ls-files | Select-String -Pattern "(^|/)\.env$|\.pem$|\.key$"
```

最后一条正常情况下没有输出。再打开GitHub的`Files changed`或仓库文件列表，确认只存在`.env.example`，不存在`.env`或`knowledge/.env`。

不要把密钥放在README、截图、实验JSON或提交信息中。如果真实密钥曾经进入Git历史，仅删除文件不够，应立即去百炼控制台吊销并重新生成。

## 七、上传后检查

分别打开两个GitHub仓库并确认：

- 首页自动渲染README、Mermaid架构图与工作流图；
- 所有截图正常显示；
- Actions标签中的CI通过；
- `.env.example`存在且只有占位符；
- Releases/仓库中没有模型、PDF、解析缓存或数据库；
- README中的启动命令能从干净目录复制执行。

最后在每个仓库右侧`About`中填写一句描述和技术标签，并把两个仓库Pin到GitHub个人主页。建议录制30—60秒GIF，但README中的静态截图已经足够完成第一版投递。

## 八、以后如何更新

在对应项目目录修改后分别执行：

```powershell
git status
git add .
git commit -m "docs: improve project demonstration"
git push
```

不要在售后智办根目录提交智维手册，也不要在两个目录之间复制`.git`文件夹。
