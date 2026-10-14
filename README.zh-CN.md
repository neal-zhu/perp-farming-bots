# Perp Farming Bots

[English](README.md) · [新手使用指南](docs/guide.zh-CN.md) · [完整文档](docs/README.md)

**想参与永续交易所的积分活动，又不想每天手动开仓、平仓、来回切换几个网站？**

Perp Farming Bots 是一个免费开源的交易工具。你在中文页面里连接自己的账户，选好策略和金额，让 Bot 执行重复的交易步骤，并在一个地方查看成交额、手续费、盈亏和已接入的积分数据。**使用策略不需要写代码。**

程序由你运行在自己的电脑或服务器上，交易使用你自己的交易所账户，API Key 保存在本地。

## 它能帮你做什么

| 你想做的事 | 工具怎么帮你 |
| --- | --- |
| 两个账户配合交易 | 一个账户做多，另一个做空；你分别选择账户、合约和金额，达到设定价差后建仓 |
| 定期重复建仓和平仓 | 设置持仓间隔，双腿平仓确认后随机等待，再按原条件建仓 |
| 让价格区间内的买卖自动执行 | 做多、做空或中性网格，按价格变化分批买卖 |
| 看清交易花了多少、发生了什么 | 每个 Bot 单独显示持仓、成交记录、累计成交额、手续费和交易盈亏 |
| 回头看积分有没有变化 | 自动记录 Lighter Robinhood 账户积分，查看历史曲线 |
| 同时管理几个账户 | 支持多个 Bot，同一交易所也可以连接多个不同账户 |

一个 **Bot** 就是一份独立的自动交易任务，有自己的账户选择、策略参数和交易记录。你可以同时创建多个 Bot。

积分是否计入、怎样分配及是否有空投，由各平台的活动规则决定；本工具不承诺积分或空投收益。

## 从哪里开始

目前支持 Arcus、Lighter Core、Lighter Robinhood、Entropy 和 Ondo Perps 的交易接入。首次使用可以先选一个已有账户的平台。

下面是维护者提供的邀请链接；使用这些链接会涉及平台的推荐关系，具体按平台邀请规则执行。

| 平台 | 进入平台 | 邀请码 |
| --- | --- | --- |
| Arcus | [通过邀请链接打开 Arcus](https://app.arcus.xyz/ref/NEAL) | `NEAL` |
| Entropy | [通过邀请链接打开 Entropy](https://entropy.io/?r=deltawillow2039) | `deltawillow2039` |
| Lighter Robinhood | [通过邀请链接打开 Lighter Robinhood](https://robinhoodchain.lighter.xyz/?referral=9264234S&source=none) | `9264234S` |

邀请链接是可选的。程序不会自动替你注册、绑定邀请码或提交钱包授权。

## 开始使用只需要这几步

1. **启动工具。** 按下面的安装步骤，在自己的电脑或服务器启动程序。
2. **连接账户。** 在平台创建交易 API Key，再到“账户实例”填写账户信息。具体填写方法见 [新手使用指南](docs/guide.zh-CN.md#连接账户)。
3. **创建 Bot。** 选择对冲或网格，填写账户、合约、交易金额等参数。
4. **点击运行。** 保存只是记住参数，点击“运行”后才开始执行策略。
5. **查看结果。** 在 Bot 页面看成交和盈亏，在积分页面看已接入的账户积分。可以暂停策略或关闭该 Bot 的仓位。

**目前自动采集的是 Lighter Robinhood 账户积分。** Arcus、Lighter Core、Entropy 和 Ondo Perps 的积分查询尚未接入，可以到各平台官网查看。交易支持范围与积分查询支持范围分别见 [平台接入说明](docs/exchanges.md)。

![中文策略页面](docs/assets/strategies.png)

## 安装与启动

首次安装需要打开终端执行下面的命令；之后通过浏览器操作，不需要编写交易策略。先安装 [uv](https://docs.astral.sh/uv/getting-started/installation/) 和 Git：

```bash
git clone https://github.com/neal-zhu/perp-farming-bots.git
cd perp-farming-bots
uv sync --frozen
uv run perp-farming-bots
```

打开 **http://127.0.0.1:8080**，开始连接账户。

已经安装 Docker 的用户，也可以在项目目录运行：

```bash
docker compose up --build -d
```

程序需要持续在线，关闭浏览器不影响运行。网格是在价格触发时提交订单，需要程序持续监测；不会提前在交易所挂出整套网格订单。

当前页面和 API 没有登录认证，默认仅供本机访问。服务器使用方式、备份和重启见 [运维说明](docs/operations.md)。

## 想进一步了解

- [新手使用指南](docs/guide.zh-CN.md)：账户填写、策略选择、参数解释、暂停和平仓。
- [对冲策略](docs/hedging.md) / [网格规则](docs/GRID.md)：详细运行规则。
- [平台接入说明](docs/exchanges.md)：账户类型、积分及费用数据的支持范围。交易盈亏暂不包含实际资金费。
- [反馈问题](https://github.com/neal-zhu/perp-farming-bots/issues)：附上操作步骤和去掉敏感信息的截图。

开发者和 coding agent 从 [AGENTS.md](AGENTS.md)、[贡献指南](CONTRIBUTING.md) 和 [代码导航](docs/development.md) 开始。应用代码使用 Apache-2.0 许可证，复用来源见 [UPSTREAMS.md](UPSTREAMS.md)。
