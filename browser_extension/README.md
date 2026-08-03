# CommandCenter 浏览器只读观察器

这是开发阶段使用的解压扩展。它只观察当前明确选择的 MES 标签页，将脱敏后的页面语义与网络证据发送到本机 CommandCenter；凭证与证据分开传输，自动验证结束后清除凭证。

## 安装与启动

1. 在项目目录启动后端：

   ```powershell
   conda run -n langgraph uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

2. 打开 `edge://extensions` 或 `chrome://extensions`。
3. 启用“开发人员模式”，选择“加载解压缩的扩展”，目录为 `D:\python\CommandCenter\browser_extension`。
4. 用户自行登录 MES。不要把账号、密码、Token、Cookie 或验证码写入项目、截图和验收记录。
5. 打开 MES 的“采购申请列表”，确认扩展显示当前选中的准确主机和只读录制状态。
6. 点击“开始录制”，仅执行一次查询并打开一条已有记录的详情。
7. 回到扩展点击“停止录制”。停止后扩展才请求中控分析并自动进行只读验证。
8. 确认结果为 `verified_candidate`；同时确认普通 `GET /skills` 不返回这个候选能力。

## 录制前安全检查

- [ ] `app/data/system_profiles/yifeng_mes.json` 只允许以下三个 `GET` 路径：
  - `/jeecg-boot/purchase/apply/list`
  - `/jeecg-boot/purchase/apply/queryById`
  - `/jeecg-boot/purchase/apply/queryPurchaseApplyDetailByMainId`
- [ ] 当前没有另一个浏览器开发者工具或调试器占用所选标签页。
- [ ] 扩展显示的主机为 `yifeng.dtsum.com`，所选标签页就是准备演示的标签页。
- [ ] 扩展显示只读模式，且后端地址仅为 `http://127.0.0.1:8000`。
- [ ] 只执行查询、翻页和查看已有详情，不触发任何业务状态变化。

## 强制停止条件

不得点击“新增、编辑、保存、提交、审核、完成、反审核、反完成、删除”，也不得尝试安全清单未明确允许的动作。页面含义不清楚、扩展选错标签页、接口超出允许清单、调试器冲突或服务报错时，应立即停止录制，并将验收结果记为 `inconclusive`，不要通过探索写操作排查。

## 数据边界

- 不记录密码和文件内容。
- URL 只保留 origin、path 和查询参数名称。
- 普通字段值默认只保存带密钥的指纹，不保存原值。
- 请求凭证单独暂存于内存，只用于自动只读验证，验证结束即清除。
- 非白名单流量可以作为脱敏观察证据，但不能生成可执行 Tool。
- 真实 MES 生成的能力停留在 `verified_candidate`，不会自动发布给任务中心。
