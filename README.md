# Perp Farming Bots

独立、自托管的永续交易策略程序，面向不需要编程的用户。通过浏览器连接交易所账户、创建多个 Bot、查看持仓、成交、盈亏和通知。

当前执行路径对接真实交易所。页面没有演示账户、虚构行情或本地撮合入口。

## 启动

需要 Python 3.12 和 [uv](https://docs.astral.sh/uv/)，或 Docker Compose。

```bash
uv sync --frozen
uv run perp-farming-bots
```

打开 `http://127.0.0.1:8080`。当前开发会话使用 `http://127.0.0.1:8088`。

```bash
docker compose up --build -d
```

本地免登录；安全方案按产品要求暂时待定。程序默认只监听本机，Compose 也仅向本机开放端口。运行数据保存在 `data/`，不进入 Git。

## 连接账户

1. 在“账户实例”点击“连接账户”，选择交易所并填写昵称。
2. **Arcus**：到 [API Keys](https://app.arcus.xyz/api-keys) 生成并授权密钥。填写钱包地址、Subaccount # 和 API Signing Key。
3. **Lighter Core / Robinhood**：在 [Core API Keys](https://app.lighter.xyz/apikeys) 或 [Robinhood API Keys](https://robinhoodchain.lighter.xyz/apikeys) 创建 API key。填写 Account Index、API key 编号和 API 私钥。Core 新建 key 使用 4–254；RH 使用 4–156 或 158–254。Core 与 Robinhood 的账户和密钥分别绑定。
4. 点击“验证并连接账户”。通过场馆校验后，页面显示实际余额和持仓。

填写的是交易所 API 签名密钥；程序不要求主钱包助记词或主钱包私钥。API 私钥加密保存在本机，不返回到列表接口。

同一交易所可以连接多个不同原生账户，例如两个 Arcus 子账户互相对冲。给同一原生账户换 API key 不会形成第二个账户。

## 创建和运行 Bot

1. 点击“创建 Bot”，选择做多账户、做空账户和币种。
2. 设置单侧目标金额、价差阈值和最大滑点，查看两边实际盘口。
3. 保存后点击“启动”。Bot 在价差达到条件时，提交有价格上限的 IOC 订单。
4. 先确认第一腿实际成交，再按已成交数量提交第二腿。部分成交只记录实际数量；不会自动重复补仓、止损或补保证金。
5. “暂停”和“停止”保留持仓；“平仓”仅提交这个 Bot 的分配数量，使用 reduce-only。

当前先开放 BTC、ETH、SOL 标准加密资产永续。不同合约单位及其他资产需要逐项核实后开放。两个同向 Bot 可共用同一个账户合约，并独立平仓；相反方向需要不同账户。

程序以可用抵押资产覆盖单侧名义金额作为初始资金检查，不自动修改交易所杠杆或保证金模式。已有外部持仓、未完成委托或未确认订单会阻止新提交，需要先核实。

## 当前接入与验证

| 交易所 | 代码能力 | 已完成验证 |
| --- | --- | --- |
| Arcus | 原生账户读取、Ed25519 订单签名、REST IOC、原订单及成交查询 | 官方目录与实际 BTC 盘口读取；签名、回执与成交解析测试 |
| Lighter Robinhood | 官方 SDK 签名、账户校验、REST IOC、原订单查询 | 官方目录与实际 BTC 盘口读取；签名参数及订单解析测试 |
| Lighter Core | 同上，独立部署和签名链 ID | 官方目录与实际 BTC 盘口读取；签名参数及订单解析测试 |
| Hyperliquid / Binance | 尚未接入账户执行 | 待开发 |

**本次开发没有使用用户的交易所凭据，也没有发送真实订单。真实账户连接及资金往返交易尚未完成实际验收。** 当前代码具备下单路径，不能把公共行情和测试通过当成实盘成交证据。

订单在提交前写入本地日志。超时、回执丢失或重启后查询原订单身份，结果未知时停止新提交；不会盲目重发。首次实现使用 REST 轮询和最近历史，超过场馆可读历史范围的订单会保持未知，等待人工核实。手续费无法完整确认时显示待确认；资金费归属和官方积分读取尚未接入，不能作为已知零值。价格盈亏与完整收益分开展示。

通知包括站内告警和可选 Telegram。异常持仓只告警，不自动执行额外风险管理交易。关闭浏览器不会停止 Bot；停止程序会停止条件监测。

## 数据和开发

本次真实执行使用 `data/app.live.db`（schema 2）。旧版本的 `app.db` 保留，不转换旧成交记录为真实交易。`docker compose down` 保留 volume。

可配置 `PFB_HOST`、`PFB_PORT`、`PFB_DATA_DIR`、`PFB_TIMEZONE`（默认 Asia/Shanghai）；`.env.example` 提供参考。本地显式加载配置可使用 `uv run --env-file .env perp-farming-bots`。

```bash
make check
make test
```

测试专用的场馆替身只存在于 `tests/`，用于验证未知订单、部分成交和多 Bot 归属；应用不提供测试市场。

## 产品和来源

第一版内置跨账户价差对冲；永续网格和剥头皮待规则明确后实现。Bot 的身份、订单和持仓归属不以对冲命名。

本项目不复制、导入或移植任何私人交易项目的代码、测试、配置、数据或内部资料。公开依赖、官方协议资料和来源登记见 [UPSTREAMS.md](UPSTREAMS.md)。许可证为 Apache-2.0，公开依赖保留各自许可证。

- [Bot 与账户实例](docs/BOTS.md)
- [当前验证与剩余事项](docs/STATUS.md)
- [实施范围](docs/IMPLEMENTATION.md)
- [完整设计与后续方向](docs/DESIGN.md)
- [真实接入协议依据](docs/research/native-execution.md)
