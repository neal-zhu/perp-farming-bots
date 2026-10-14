# Perp Farming Bots

[English](README.md) · [使用指南](docs/guide.zh-CN.md) · [文档目录](docs/README.md)

一个自托管的永续交易 Bot 工具。通过浏览器连接自己的交易所账户、创建多个 Bot，查看各自的持仓、成交、盈亏和累计成交额，不需要编写策略代码。页面为简体中文。

目前提供两种策略：**跨账户价差对冲**与**做多、做空、中性永续网格**。支持同一交易所的多个账户实例，例如两个 Arcus 子账户之间对冲。

## 启动

安装 [uv](https://docs.astral.sh/uv/getting-started/installation/) 和 Git，然后执行：

```bash
git clone https://github.com/neal-zhu/perp-farming-bots.git
cd perp-farming-bots
uv sync --frozen
uv run perp-farming-bots
```

打开 **http://127.0.0.1:8080**。依次连接账户、创建 Bot、点击“运行”。保存参数本身不会启动交易。

也可以使用 Docker Compose：

```bash
docker compose up --build -d
```

**目前没有登录认证，仅供本机访问。** 默认地址和 Compose 端口均限制在本机。端口、服务器访问、备份和重启方法见 [运维说明](docs/operations.md)。

## 支持范围

交易接入：Arcus、Lighter Core、Lighter Robinhood、Entropy。策略支持 BTC、ETH、SOL。

- 对冲：两个不同账户、一个币种，设置价差条件和单侧目标金额；可定期平仓后重新等待建仓条件。
- 网格：一个账户，设置方向、固定价格区间、格数、保证金额度、杠杆和保证金模式。程序等待价格触发后提交 IOC 订单，需要持续在线。
- 积分：当前采集 Lighter Robinhood 自己账户的实时积分，提供历史曲线。其他平台显示“暂未接入”。
- Entropy：使用主交易账户地址和 API 代理密钥；暂不支持统一/组合保证金、子账户、Vault 和自有 HIP-3 合约。

完整的账户填写方法、保证金计算、初始建仓、暂停与平仓、故障处理见 [使用指南](docs/guide.zh-CN.md)。

![策略库](docs/assets/strategies.png)

## 数据与执行

订单先记账再发送；结果不明时查询原订单，不重复下单。临时读取失败会重试，持续 5 分钟不可用才暂停。暂停保留仓位，平仓仅处理所选 Bot 的分配数量。

交易盈亏扣除已确认手续费，暂不包含实际资金费。积分和资金费率预估单独展示，未知数据不会填成 0。自动化测试不等于各交易所已经完成实盘验收，也不代表积分奖励资格。

运行数据与本地加密密钥保存在 `data/`，不进入 Git。程序使用本地 SQLite，无需另外安装数据库。

## 开发与贡献

```bash
make check
make test
```

开发者和 coding agent 从 [AGENTS.md](AGENTS.md)、[贡献指南](CONTRIBUTING.md) 和 [代码导航](docs/development.md) 开始。协议依据和复用来源登记在 [UPSTREAMS.md](UPSTREAMS.md)。应用代码使用 Apache-2.0 许可证。
