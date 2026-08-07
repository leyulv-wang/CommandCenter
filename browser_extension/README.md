# CommandCenter 演示观察器

该扩展采用 Browser-BC 的 WXT/TypeScript 录制器作为技术底座，记录员工在业务系统中的
页面操作、DOM 语义和页面 JavaScript 发出的 API 请求，并把脱敏证据上传到本机
CommandCenter。中控智能体负责页面操作与 API Tool 对齐、Skill 生成、无害测试和发布。

## 构建和加载

```powershell
cd D:\python\CommandCenter\browser_extension
pnpm install --frozen-lockfile
pnpm test
pnpm typecheck
pnpm build
pnpm test:e2e:local
```

`test:e2e:local` 会自动启动中控和本地采购系统，用真实 Chromium 扩展录制一次只读的
“刷新申请记录”操作，等待智能体生成并验证 API Skill，并确认采购数据没有变化。首次运行
前如本机尚无 Playwright Chromium，可执行 `pnpm exec playwright install chromium`。

在 Chrome 或 Edge 的扩展管理页面启用开发者模式，选择“加载解压缩的扩展”，加载：

```text
D:\python\CommandCenter\browser_extension\dist\chrome-mv3
```

代码更新后需要重新运行 `pnpm build`，并在扩展管理页面点击“重新加载”。

## 启动中控

```powershell
cd D:\python\CommandCenter
conda run -n langgraph python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## 录制步骤

1. 用户自行登录已配置的业务系统。
2. 打开准备演示的业务页面。
3. 打开扩展，确认显示的系统和域名正确。
4. 输入清晰的演示目标，例如“查询采购申请”。
5. 点击“开始录制”，完成一次正常业务操作。
6. 点击“停止录制并学习”。
7. 扩展显示证据是否已提交；中控在后台继续学习、测试和发布。

刷新页面或扩展后台休眠时，本地录制和待上传证据保存在 IndexedDB 中。上传失败不会删除
本地证据，可以继续恢复上传。

## 当前 MES 安全边界

真实 MES 测试只执行查询、翻页和查看已有详情。不得点击新增、编辑、保存、提交、审核、
完成、反审核、反完成或删除。当前后端 Tool 白名单仍是最终执行边界，未允许的请求只能作为
观察证据，不能生成可执行 Tool。

录制状态只会在当前系统配置允许的精确 origin 中启用。录制 MES 时切换到其他网站，不会把
其他网站的操作加入本次轨迹。

## 隐私边界

- 不上传密码、Cookie、Authorization、Token、文件内容和原始剪贴板内容。
- 表单值、选择器和请求体只以带密钥指纹进入中控证据。
- URL 仅保留 origin、path 和查询参数名称。
- 单次录制令牌仅保存在扩展本地会话中，不写入 Skill。

## 网络观察能力范围

扩展通过注入页面脚本包装 `fetch`、XHR 和 Beacon，并记录 WebSocket/EventSource 的连接
元数据，因此不需要 `chrome.debugger` 权限。该方法不会覆盖所有浏览器流量：注入前已发生
的请求、Service Worker 请求、浏览器自身请求和其他扩展请求可能不可见。遇到这种情况，
中控会保留页面证据，不会伪造 API 对齐结果。

## 上游来源

具体来源和采用提交见 [UPSTREAM.md](UPSTREAM.md)。Browser-BC 的 Python 服务、控制面板、
Claude Skill 安装器和蒸馏 Harness 未进入 CommandCenter 运行链路。
