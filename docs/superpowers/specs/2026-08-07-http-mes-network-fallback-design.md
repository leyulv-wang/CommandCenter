# HTTP MES 网络观察兜底设计

## 背景与结论

真实益丰 MES 的“采购申请查询”会调用已公开在 OpenAPI 中的只读接口：

- `GET /jeecg-boot/purchase/apply/list`
- `GET /jeecg-boot/purchase/apply/queryById`
- `GET /jeecg-boot/purchase/apply/queryPurchaseApplyDetailByMainId`

2026-08-07 的真实录制记录到了筛选条件和“查 询”按钮，共 16 条 UI 事件，但网络交换为
0。浏览器控制台同时显示扩展在 HTTP 页面调用 `crypto.subtle.digest` 失败。这里的“0”表示
观察器漏采，不表示 MES 没有调用 API。

## 目标

让扩展在 HTTPS、localhost 和普通 HTTP 企业系统中都能可靠生成网络元数据证据，同时保持：

1. 不读取 Cookie、Authorization、Token 或响应正文。
2. 不因为观察网络而执行额外业务请求。
3. 不使用接口名称、业务关键词或时间阈值硬编码判断。
4. 页面丰富证据可用时继续优先使用；不可用时自动采用浏览器级兜底证据。

## 方案

### HTTP 指纹兼容

`sha256Hex` 优先使用 Web Crypto。当前上下文没有 `crypto.subtle` 时，改用仓库已有的纯
TypeScript SHA-256 算法处理相同字节，输出保持一致。降级只由平台能力决定，不由域名或
业务系统决定。

### webRequest 兜底观察器

扩展后台使用现有 `webRequest` 权限观察录制期间的请求：

- `onBeforeRequest`：记录请求 ID、标签页、方法、完整 URL 和开始时间。
- `onCompleted` / `onErrorOccurred`：记录状态码、完成时间或安全错误类别。
- 只接受当前录制允许 origin 内、来自已连接录制标签页的 HTTP(S) 请求。
- 不记录请求头、响应头、Cookie、令牌、请求正文或响应正文。
- 记录继续经过现有 CommandCenter 脱敏转换，只上传 origin、path、查询参数名、状态码和
  指纹。

兜底事件在本地标记 `capture_channel=browser_web_request`。

### 通道选择与去重

停止录制并上传前，按整条 trace 做确定性选择：

1. 如果存在页面注入通道的 HTTP 网络请求，上传页面通道，忽略 webRequest 兜底事件。
2. 如果页面注入通道的 HTTP 网络请求为 0，上传 webRequest 兜底事件。
3. UI、DOM、表单、导航和流式连接证据不受该选择影响。

该策略不设置毫秒窗口、不根据 URL 名称推断，也不会把同一端点的两次真实请求错误合并。

## 状态与错误处理

- webRequest 监听器只在录制激活时写入证据。
- 停止、失败或扩展恢复时清理当前请求映射，避免跨录制串线。
- 缺少标签页、非法 URL、非 HTTP(S) 或不允许 origin 的请求直接忽略。
- 页面通道失败不会终止 UI 录制；兜底通道仍可生成最小 API 证据。
- 两个网络通道都没有证据时保持现有行为，生成浏览器候选而不是伪造 API Skill。

## 安全边界

webRequest 只是观察层。后端 `SystemProfile.tool_permissions` 仍是可执行 Tool 的最终白名单。
益丰 MES 当前只允许三个 GET 查询 Tool；新增、编辑、删除、送审、完成等写接口即使被观察
到，也不能成为可执行 Skill。

## 测试与验收

自动测试必须覆盖：

1. 没有 `crypto.subtle` 时 SHA-256 输出与标准向量一致。
2. webRequest 只记录当前录制标签页和允许 origin。
3. 请求与响应可以按浏览器 request ID 配对。
4. 页面通道存在时排除兜底副本；页面通道缺失时晋升兜底证据。
5. 停止与异常后清理请求状态。
6. 现有本地真实扩展端到端测试、扩展单元测试、后端测试和前端测试全部通过。

人工只读验收重新录制一次益丰 MES“采购申请查询”。成功标准是后端 trace 至少包含
`GET /jeecg-boot/purchase/apply/list`，匹配 `yifeng_mes:listPurchaseApply`，且没有执行任何
写请求。
