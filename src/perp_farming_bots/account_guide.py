"""Public, credential-free onboarding help, packaged with the application."""

from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException
from nicegui import app, ui

from .models import PROVIDER_NAMES, Provider

ASSET_DIR = Path(__file__).parent / "assets" / "api-guide"
ASSET_URL = "/help-assets/api-guide"
GUIDE_URL = "/help/api"


@dataclass(frozen=True)
class AccountGuide:
    summary: str
    links: tuple[tuple[str, str], ...]
    steps: tuple[tuple[str, str], ...]
    fields: tuple[tuple[str, str, str], ...]
    image: str
    caption: str
    notice: str
    questions: tuple[tuple[str, str], ...]
    reference: str


def lighter_guide(*, robinhood: bool) -> AccountGuide:
    name = "Lighter Robinhood" if robinhood else "Lighter Core"
    host = "robinhoodchain.lighter.xyz" if robinhood else "app.lighter.xyz"
    return AccountGuide(
        summary="准备 3 项：Account Index、API key 编号、API 私钥。",
        links=((f"打开 {name} API Keys", f"https://{host}/apikeys"),),
        steps=(
            ("连接要使用的钱包", f"打开 {host} 的 API Keys 页面，点击 Connect Wallet。确认选中的是要交给 Bot 使用的账户。"),
            ("创建交易 API 密钥", "在 API Keys 创建用于交易的密钥，完成官网要求的钱包签名，并保存 API 私钥。只读 Token 和 Maker-only 密钥不适用于本工具的交易策略。"),
            ("记下两个不同的编号", "记录这个账户的 Account Index，以及刚才密钥对应的 API key index。它们分别代表账户和密钥，不能相互替代。"),
            ("回到本工具验证", f"选择 {name}，把下面 3 个字段填齐，再点击“验证并连接账户”。不要选择另一个 Lighter 部署。"),
        ),
        fields=(
            ("Account Index", "所选交易账户的 Account Index", "填写整数账户编号，不是 0x 钱包地址；使用子账户时填写该子账户自己的编号。"),
            ("API key 编号", "该账户下刚创建的 API key index", "填写官网显示的密钥编号。255 表示查询全部密钥，不是一个可用于交易的密钥编号。"),
            ("API Signing Key", "生成密钥时保存的 API Private Key", "填写私钥，不是 API 公钥、Auth Token 或只读 Token。"),
        ),
        image="lighter-robinhood-api.jpg" if robinhood else "lighter-core-api.jpg",
        caption=f"{name} API Keys 官方入口，未连接钱包。先核对域名，再点 Connect Wallet。",
        notice="Core 与 Robinhood 的密钥分别创建、分别使用。即使两个编号碰巧相同，也不能混用。",
        questions=(
            ("找不到 Account Index？", "先在官网切换到目标账户，查看 API Keys 或账户信息中的 Account Index。若页面没有显示，可按下方官方文档的 Find Your Account Index 查询；不要把钱包地址或 API key 编号当成账户编号。"),
            ("提示密钥不匹配或账户不存在？", f"核对官网是否为 {host}，再核对 Account Index、API key 编号和私钥是否来自同一个账户、同一次密钥创建。"),
            ("应该手动选哪个密钥编号？", "优先使用官网提供的可用编号。Core 官方文档保留 0–3；Robinhood 还保留 157，供网页或移动端使用。为 Bot 创建独立密钥，不要覆盖正在使用的密钥。"),
        ),
        reference="https://apidocs.rh.lighter.xyz/docs/get-started" if robinhood else "https://apidocs.lighter.xyz/docs/get-started",
    )


GUIDES = {
    Provider.ARCUS: AccountGuide(
        summary="准备 3 项：钱包地址、子账户编号、API Signing Key。",
        links=(("打开 Arcus API Keys", "https://app.arcus.xyz/api-keys"),),
        steps=(
            ("登录 Arcus", "打开 API Keys 页面，点击 Sign in，使用准备交给 Bot 交易的钱包登录。"),
            ("生成并授权密钥", "给 API 密钥起一个容易识别的名字，例如 Perp Farming Bots，点击 Generate，再按官网提示完成 Authorize 钱包授权。"),
            ("保存签名密钥并核对账户", "保存官网生成的 API Signing Key，记录钱包地址，并核对要交易的 Subaccount #（子账户编号）。"),
            ("回到本工具验证", "选择 Arcus，填写账户昵称和以下字段，再点击“验证并连接账户”。验证通过后才会保存账户。"),
        ),
        fields=(
            ("钱包地址", "登录 Arcus 的主钱包地址", "完整的 0x 地址，不是 API 公钥。"),
            ("子账户编号", "要交易的 Subaccount #", "填写 0–9 的整数；默认账户通常为 0，以官网当前选中的账户为准。"),
            ("API Signing Key", "生成时保存的 Ed25519 API 签名私钥", "填写完整签名密钥，不是 API Key 公钥，也不是登录钱包的私钥。"),
        ),
        image="arcus-api.jpg",
        caption="Arcus API Keys 官方入口，未登录。中间一行是名称、Generate 和 Authorize 的位置。",
        notice="生成密钥后还要完成官网授权；只有生成、没有授权的密钥不能连接。",
        questions=(
            ("提示名称不能为空？", "本工具的“账户昵称”也需要填写，例如“Arcus 账户 A”；它与官网的 API 密钥名称是两个不同的名称。"),
            ("提示密钥未注册或授权过期？", "回 Arcus API Keys 检查密钥是否已 Authorize、是否过期，并确认登录钱包与填写的钱包地址一致。"),
            ("连接后余额与官网对不上？", "先核对子账户编号。不同子账户是不同的交易账户；请比较相同子账户的永续余额。"),
        ),
        reference="https://docs.arcus.xyz/api-reference/authentication",
    ),
    Provider.LIGHTER: lighter_guide(robinhood=False),
    Provider.LIGHTER_RH: lighter_guide(robinhood=True),
    Provider.ENTROPY: AccountGuide(
        summary="准备 2 项：主交易账户地址、已授权的 API 代理私钥。需要先完成 Entropy 的交易授权。",
        links=(("① 打开 Entropy", "https://entropy.io"), ("② 打开 Hyperliquid API", "https://app.hyperliquid.xyz/API")),
        steps=(
            ("先在 Entropy 完成交易授权", "在 Entropy 官网连接要交易的钱包，按页面提示完成交易授权。只连接钱包、没有完成交易授权时，本工具会提示授权尚未完成。"),
            ("用同一主账户打开 Hyperliquid API", "Entropy 使用 Hyperliquid 的 API 代理。进入 Hyperliquid API 页面，连接与 Entropy 相同的主交易账户。"),
            ("创建有名称的 API 代理", "填写 API Wallet Name，例如 Perp Farming Bots，点击 Generate，保存生成的代理私钥，再按官网流程授权。不要覆盖其他程序正在使用的同名代理。"),
            ("把主账户地址与代理私钥带回来", "在本工具选择 Entropy。钱包地址填主交易账户地址；API Signing Key 填刚创建的代理私钥。两者对应同一个主账户后再验证。"),
        ),
        fields=(
            ("钱包地址", "Entropy 与 Hyperliquid 使用的主交易账户地址", "填写持有交易资金的主账户地址；不要复制截图中 API Wallet Address 一列的代理地址。"),
            ("API Signing Key", "Generate 时保存的 API Wallet / Agent 私钥", "填写代理私钥，不是 API Wallet Address，不是主钱包私钥。无需账户编号或 API key 编号。"),
        ),
        image="hyperliquid-api.jpg",
        caption="Hyperliquid API 官方入口，未连接钱包。这里创建的是供 Entropy 使用的 API 代理。",
        notice="支持标准账户和统一账户（Unified Account）；暂不支持组合保证金（Portfolio Margin）、子账户或 Vault。",
        questions=(
            ("提示“请先在 Entropy 官网完成交易授权”？", "回 Entropy 官网，用相同主账户完成其交易授权，再回本工具重新验证。Hyperliquid 的 API 代理授权与 Entropy 的交易授权都需要完成。"),
            ("提示代理密钥未授权或过期？", "检查 API 页面上的代理是否已授权、是否在有效期内，并确认创建代理时连接的主账户与填写的地址一致。"),
            ("统一账户、组合保证金、全仓是同一个概念吗？", "不是。标准/统一/组合描述账户余额的组织方式，全仓/逐仓描述合约的保证金方式。普通统一账户可以连接；组合保证金目前不能连接，不能仅通过修改合约杠杆解决。"),
        ),
        reference="https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/nonces-and-api-wallets",
    ),
    Provider.ONDO: AccountGuide(
        summary="准备 2 项：API Key ID、API Secret。选择 View & Trade 权限。",
        links=(("打开 Ondo Perps API Keys", "https://app.ondoperps.xyz/account/api-keys"),),
        steps=(
            ("登录 Ondo Perps", "在官网登录要使用的账户，进入账户页左侧的 API Keys。未登录时，链接可能先跳到账户概览。"),
            ("创建 View & Trade 密钥", "点击 Add New API Key，填写名称，选择 View & Trade，再点击 Create API Key。不需要 Transfer 转账权限。"),
            ("保存完整 ID 和 Secret", "复制带 ondoKeyId_ 前缀的 ID，以及带 ondoApiSecret_ 前缀的 Secret。Secret 创建时显示，请当场妥善保存。"),
            ("回到本工具验证", "选择 Ondo Perps，粘贴两项凭据并验证。账户 ID 会自动识别，不用另填钱包地址、账户编号或浏览器 Token。"),
        ),
        fields=(
            ("API Key ID", "API Keys 列表或创建结果中的 Key ID", "保留完整 ondoKeyId_ 前缀，不是账户 ID。"),
            ("API Secret", "创建密钥时显示的 Secret", "保留完整 ondoApiSecret_ 前缀，不要复制成 Key ID。"),
        ),
        image="ondo-api-entry.jpg",
        caption="Ondo Perps 未登录的账户页。左侧 API Keys 是密钥入口，登录后进入列表。",
        notice="如果设置 IP 白名单，允许的应是运行 Bot 的电脑或服务器的出口 IPv4，而不是浏览器所在设备的地址。",
        questions=(
            ("提示权限不足？", "检查密钥是否为 View & Trade；只读密钥不能执行策略，无需额外开启 Transfer。"),
            ("提示 IP 不允许或 401？", "若密钥设置了 IP 白名单，核对程序运行主机的出口 IPv4 是否在名单内；同时检查密钥是否有效。"),
            ("为什么不用填写账户编号？", "程序用 Key ID 和 Secret 验证后，读取并绑定它们所属的原生账户。该接入不提供子账户切换。"),
        ),
        reference="https://docs.ondoperps.xyz/api-reference/api_key_authentication",
    ),
}

GUIDE_STYLES = """
body { background: #f4f6f9; color: #17243b; }
.api-guide { max-width: 1120px; margin: 0 auto; padding: 32px 24px 64px; gap: 24px; }
.api-guide .q-btn { text-transform: none; border-radius: 9px; }
.api-guide h1 { font-size: 30px; line-height: 1.3; font-weight: 750; margin: 0; }
.api-guide h2 { font-size: 23px; line-height: 1.4; font-weight: 700; margin: 0; }
.api-guide h3 { font-size: 16px; line-height: 1.5; font-weight: 650; margin: 0; }
.api-intro { color: #607087; font-size: 14px; line-height: 1.8; }
.api-safety { background: #ecfdf5; border: 1px solid #ccebdc; border-radius: 12px; padding: 14px 18px; }
.api-tabs { background: white; border: 1px solid #e1e7ef; border-radius: 12px; width: 100%; }
.api-tabs .q-tab { font-weight: 650; min-height: 52px; padding: 0 18px; }
.api-panels { background: transparent; width: 100%; }
.api-panel { padding: 0; }
.api-sheet { background: white; border: 1px solid #e1e7ef; border-radius: 16px; padding: 26px; width: 100%; gap: 24px; }
.api-top { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-start; gap: 18px; width: 100%; }
.api-links { display: flex; flex-wrap: wrap; gap: 8px; }
.api-notice { border-left: 3px solid #059669; background: #f0faf5; padding: 12px 16px; color: #285b49; border-radius: 0 8px 8px 0; width: 100%; font-size: 13px; line-height: 1.8; }
.api-body { display: grid; grid-template-columns: 1fr 1.05fr; gap: 28px; width: 100%; align-items: start; }
.api-steps { display: flex; flex-direction: column; gap: 23px; }
.api-step { display: flex; gap: 12px; align-items: flex-start; }
.api-number { border-radius: 50%; width: 28px; height: 28px; flex: 0 0 28px; background: #e9f6ef; color: #047857; font-weight: 700; display: grid; place-items: center; }
.api-step p { font-size: 13px; color: #607087; line-height: 1.85; margin: 6px 0 0; }
.api-figure { margin: 0; border: 1px solid #dce4ee; border-radius: 12px; overflow: hidden; background: #f8fafc; }
.api-figure img { display: block; width: 100%; height: auto; }
.api-figure figcaption { font-size: 12px; color: #607087; line-height: 1.8; padding: 12px 14px; }
.api-photo-note { color: #8793a5; font-size: 11px; line-height: 1.7; }
.api-copy-heading { display: flex; align-items: center; gap: 9px; }
.api-fields { width: 100%; display: grid; gap: 10px; }
.api-field { display: grid; grid-template-columns: 165px 1fr; border: 1px solid #e1e7ef; border-radius: 10px; overflow: hidden; }
.api-field-label { background: #f8fafc; font-size: 13px; font-weight: 650; padding: 15px 16px; }
.api-field-copy { padding: 13px 16px; font-size: 13px; line-height: 1.8; }
.api-field-hint { color: #748196; font-size: 12px; }
.api-help { border-top: 1px solid #e7edf3; padding-top: 20px; width: 100%; }
.api-help .q-expansion-item { font-size: 13px; }
.api-help-answer { color: #607087; font-size: 13px; line-height: 1.9; padding: 0 16px 16px; }
@media (max-width: 760px) {
  .api-guide { padding: 20px 14px 40px; gap: 18px; }
  .api-guide h1 { font-size: 25px; }
  .api-sheet { padding: 19px 16px; gap: 20px; }
  .api-body { grid-template-columns: 1fr; gap: 24px; }
  .api-field { grid-template-columns: 1fr; }
  .api-field-label { padding: 9px 13px; }
  .api-field-copy { padding: 10px 13px; }
  .api-tabs .q-tab { padding: 0 13px; }
}
"""


def guide_url(provider: Provider | str = Provider.ARCUS) -> str:
    return f"{GUIDE_URL}?provider={Provider(provider).value}"


def render_guide(provider: Provider) -> None:
    guide = GUIDES[provider]
    with ui.column().classes("api-sheet"):
        with ui.element("div").classes("api-top"):
            with ui.column().classes("gap-1"):
                ui.label(PROVIDER_NAMES[provider]).mark("guide-venue").style("font-size:23px;font-weight:700")
                ui.label(guide.summary).classes("api-intro")
            with ui.element("div").classes("api-links"):
                for label, target in guide.links:
                    ui.link(label, target, new_tab=True).classes(
                        "bg-emerald-600 text-white px-4 py-2 rounded-lg text-sm font-semibold no-underline"
                    ).props('rel="noopener noreferrer"')
        ui.label(guide.notice).classes("api-notice")
        with ui.element("div").classes("api-body"):
            with ui.element("div").classes("api-steps"):
                for index, (title, text) in enumerate(guide.steps, 1):
                    with ui.element("div").classes("api-step"):
                        ui.label(str(index)).classes("api-number")
                        with ui.element("div"):
                            ui.html(f"<h3>{title}</h3>")
                            ui.label(text).classes("api-intro").style("font-size:13px; margin-top:5px")
            with ui.column().classes("w-full gap-3"):
                with ui.element("figure").classes("api-figure"):
                    with ui.link(target=f"{ASSET_URL}/{guide.image}", new_tab=True).props(
                        'rel="noopener noreferrer" aria-label="放大官方入口截图"'
                    ):
                        ui.element("img").props.update({
                            "src": f"{ASSET_URL}/{guide.image}",
                            "alt": guide.caption,
                            "loading": "lazy",
                        })
                    with ui.element("figcaption"):
                        ui.label(guide.caption)
                        ui.label("点击图片放大 · 官方页面截图于 2026-10-16，界面可能更新。").classes("api-photo-note")
                with ui.column().classes("gap-1 px-1"):
                    ui.label("截图展示入口；连接钱包后的密钥创建步骤见步骤说明。").classes("api-photo-note")
                    ui.label("创建与授权在官网完成，本工具不会替你创建密钥。").classes("api-photo-note")
        with ui.column().classes("w-full gap-3"):
            with ui.row().classes("api-copy-heading"):
                ui.icon("content_copy", size="18px").classes("text-emerald-600")
                ui.html("<h3>回到连接表单，照这样填写</h3>")
            with ui.element("div").classes("api-fields"):
                for label, source, hint in guide.fields:
                    with ui.element("div").classes("api-field"):
                        ui.label(label).classes("api-field-label")
                        with ui.element("div").classes("api-field-copy"):
                            ui.label(source)
                            ui.label(hint).classes("api-field-hint")
            ui.label("账户昵称由你自己起，例如“账户 A”；填完点击“验证并连接账户”。验证通过后，才可以为该账户创建 Bot。").classes("api-intro").style("font-size:12px")
        with ui.column().classes("api-help gap-2"):
            ui.html("<h3>遇到问题</h3>")
            for question, answer in guide.questions:
                with ui.expansion(question, group=f"help-{provider.value}").classes("w-full"):
                    ui.label(answer).classes("api-help-answer")
            ui.link("查看官方 API 说明 ↗", guide.reference, new_tab=True).classes("text-xs text-slate-500").props(
                'rel="noopener noreferrer"'
            )


def install_account_guide() -> None:
    # Only the checked-in public help images are served, never the data directory.
    app.add_static_files(ASSET_URL, ASSET_DIR)

    @ui.page(GUIDE_URL)
    async def account_guide(provider: str = Provider.ARCUS.value):
        if provider not in GUIDES:
            raise HTTPException(status_code=404, detail="没有这个交易所的 API 配置指南")
        ui.colors(primary="#059669")
        ui.page_title("API 配置指南 · Perp Farming Bots")
        ui.add_head_html('<meta name="viewport" content="width=device-width, initial-scale=1">')
        ui.add_css(GUIDE_STYLES)
        with ui.column().classes("api-guide w-full"):
            with ui.row().classes("w-full justify-between items-center"):
                ui.link("← 返回工作台", "/").classes("text-sm text-slate-500 no-underline")
                ui.label("Perp Farming Bots / 使用帮助").classes("text-xs text-slate-400")
            with ui.column().classes("gap-2"):
                ui.html("<h1>API 配置指南</h1>")
                ui.label("选好交易所，按步骤创建交易 API，再把对应信息填回账户页。").classes("api-intro")
            with ui.row().classes("api-safety w-full items-center gap-3"):
                ui.icon("key", size="22px").classes("text-emerald-700")
                ui.label("这里只填写交易 API 密钥。不要填写主钱包私钥或助记词，也不要把密钥截图发给他人。").classes("text-sm text-emerald-900")
            with ui.tabs().classes("api-tabs").props("align=left no-caps mobile-arrows outside-arrows") as tabs:
                for venue in GUIDES:
                    tab = ui.tab(venue.value, label=PROVIDER_NAMES[venue])
                    if venue.value == provider:
                        tabs.set_value(tab)
            with ui.tab_panels(tabs, value=provider).classes("api-panels"):
                for venue in GUIDES:
                    with ui.tab_panel(venue.value).classes("api-panel"):
                        render_guide(venue)
