# CommandCenter 浏览器只读观察器

这是开发阶段使用的解压扩展。默认只观察当前明确选择的 MES 标签页，将脱敏后的页面语义发送到本机 CommandCenter。网络调试是可选能力，默认不启用，因此普通录制不会接管或调试当前标签页。

## 安装与启动

1. 在项目目录启动后端：

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

2. 打开 `edge://extensions` 或 `chrome://extensions`。
3. 启用“开发人员模式”，选择“加载解压缩的扩展”，目录为 `D:\python\CommandCenter\CommandCenter\browser_extension`。代码更新后必须在扩展页面点击“重新加载”，确认版本为 `0.3.2`。
4. 用户自行登录 MES。不要把账号、密码、Token、Cookie 或验证码写入项目、截图和验收记录。
5. 打开 MES 的“采购申请列表”，确认扩展显示当前选中的准确主机和只读录制状态。
6. 点击“开始录制”，仅执行一次查询；不要求打开详情。
7. 回到扩展点击“停止录制”。录制证据会立即保存，后台继续分析，扩展可随后查询进度。
8. 有可靠 API 证据时结果可进入 `verified_candidate`；仅有页面证据时生成 `browser_candidate`，等待以后在隔离浏览器中验证。

默认不要勾选“同时观察 API”。只有明确需要重新尝试 API 映射，并接受浏览器显示调试提示时才勾选；该选择不会改变只读白名单。

## 录制前安全检查

- [ ] `app/data/system_profiles/yifeng_mes.json` 只允许以下三个 `GET` 路径：
  - `/jeecg-boot/purchase/apply/list`
  - `/jeecg-boot/purchase/apply/queryById`
  - `/jeecg-boot/purchase/apply/queryPurchaseApplyDetailByMainId`
- [ ] 扩展显示的主机为 `yifeng.dtsum.com`，所选标签页就是准备演示的标签页。
- [ ] 扩展显示只读模式，且后端地址仅为 `http://127.0.0.1:8000`。
- [ ] 只执行查询、翻页和查看已有详情，不触发任何业务状态变化。

## 强制停止条件

不得点击“新增、编辑、保存、提交、审核、完成、反审核、反完成、删除”，也不得尝试安全清单未明确允许的动作。页面含义不清楚、扩展选错标签页、接口超出允许清单、调试器冲突或服务报错时，应立即停止录制，并将验收结果记为 `inconclusive`，不要通过探索写操作排查。

## 数据边界

- 不记录密码和文件内容。
- URL 只保留 origin、path 和查询参数名称。
- 普通字段值默认只保存带密钥的指纹，不保存原值。
- 默认语义录制不读取请求凭证；启用可选 API 观察时，凭证与证据分开暂存，并在验证结束后清除。
- 非白名单流量可以作为脱敏观察证据，但不能生成可执行 Tool。
- 真实 MES 生成的能力停留在 `verified_candidate` 或 `browser_candidate`，不会自动发布给任务中心。
