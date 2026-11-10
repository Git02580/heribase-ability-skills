# HeriBase CLI 命令参考

## 通用规则

- `heribase -h` / `heribase --help` 查看总览；`heribase <命令路径> --help`（也支持 `-h`）查看命令组或子命令帮助，无需配置和登录。例如 `heribase collection update --help`、`heribase file upload --help`、`heribase appraisals submit --help`。
- 业务命令、任务命令和状态检查均追加 `--json`。
- 每个业务操作可选 `--mode sync|async`，默认 `sync`。
- CLI 自动通过本机 daemon 调度业务操作；不要直接调用 `__daemon` 或 `__worker` 内部入口。
- 所有识别和收藏业务事实都以服务端响应为准。CLI 的本地 daemon 状态不是长期业务数据源；采用 `heribase-task-package` 时，要把精确 stdout JSON 与规范化投影双层保存，但不得把本地投影冒充服务端事实。
- 已确认批量中的原子业务命令可追加 `--batch-id <id> --candidate-id <id>`。两者必须成对提供，仅保存到本地任务上下文和历史索引，绝不作为 Agent API 参数发送。标识仅允许字母、数字、`_` 与 `-`，最长 128 个字符。
- CLI 对所有 `/agent/v1` 请求自动附带 `docs/api/agent_api.md` 3.9 定义的 Agent 创建来源 `User-Agent`：`AGENT/<harness>;AGENTVERSION/<CLI 版本>;OSVER/<系统名 版本>`。`harness` 会识别 OpenClaw、Hermes、OpenCode、Gemini CLI、Cursor Agent、Claude Code 和 Codex；未识别的 Harness 可通过 `HERIBASE_AGENT_HARNESS` 显式声明。业务 Skill 不得手工覆盖该请求头，也不得发送已废弃的 `APPVER`、`OS`、`DEVMODEL`、`NETWORK` 字段。

## 配置与认证

```bash
heribase configure --api-base-url <url> [--lang <lang>] [--max-workers <n>]
heribase login
heribase logout
heribase status --json
```

- 首次使用自动初始化官方 API `https://api.heribase.com`；已有配置优先，首次初始化的 `HERIBASE_API_BASE_URL` 可覆盖默认值。帮助和版本查询不创建配置。
- `configure` 用于自定义 API 地址、语言和最大 Worker 数；普通用户可直接 `login`，无需先配置。它不会保存 token。
- `login` 打开浏览器并接收本机回调；需要用户完成网页登录。
- `status --json` 用于确认 CLI 是否已配置、是否具有凭据；新版额外返回可用的稳定非敏感 `accountSubject`，供工作空间绑定确认范围。
- `api profile --json` 供工作台显示当前授权方式和可用的账号昵称、头像；不返回凭据，也不创建或归档业务任务。
- 服务端返回未授权时，让用户重新登录，不尝试刷新或手工编辑 token。

## API 连通性诊断

```bash
heribase api check --json
```

- 通过 daemon 分别检查配置 host 的 DNS、TCP、TLS 建连，并请求需认证的 `GET /agent/v1/health` 空参数只读接口。
- 探测使用固定 10 秒连接超时，不读取 `config.json` 的 `connectTimeoutMs`；普通业务请求继续使用自己的配置值。
- 输出分开报告 host 阶段和 API 阶段；API 错误会保留 HTTP 状态、服务端错误码或传输诊断。探测不创建本地业务任务，也不读取追踪位或其他业务数据。
- `UNAUTHENTICATED` 表示 host/API 已可达但凭据未通过；`DOWNSTREAM_UNAVAILABLE` 应结合 DNS/TCP/TLS 与 fetch 诊断阶段判断。
- 业务任务执行终态为 `failed`，且任务错误为 `DOWNSTREAM_UNAVAILABLE` 或传输详情包含 `UND_ERR_CONNECT_TIMEOUT` 时，同步命令以及后续 `task get/wait` 会自动补做一次该只读检查，并在任务结果中附加 `apiConnectivityCheck`。原任务错误会保留，业务请求不会因此重放；其他业务错误不触发检查。

## 图片上传

```bash
heribase file upload --file <local-path> --json
```

CLI 会检查图片尺寸与格式，通过 `multipart/form-data` 调用 `POST /agent/v1/file/upload`，由 API 接收并上传图片。CLI 自动传入 `type=1`、`mode=1`、`scene=identify` 和本次请求的 `uuid`，保留响应中的 `url`、`file`、`thumb`，并将 `url` 映射为兼容字段 `fileUrl`。成功响应至少包含：

```json
{
  "fileUrl": "https://cdn.example.com/sky/agent/identify/image/front.jpg",
  "suffix": "jpg",
  "width": 1200,
  "height": 1200
}
```

支持 `jpg`、`jpeg`、`png`、`webp`、`heic`、`heif`，宽高均至少 200 像素。HEIC/HEIF 可直接上传，无需转换；CLI 根据图片二进制检查格式并读取尺寸。只有在用户已确认图片要离开本机并进入识别流程后才上传。

若只需要申请上传目标而不直传文件，可使用：

```bash
heribase file pre-upload --suffix <suffix> --width <n> --height <n> [--content-type <mime>] --json
```

`file pre-upload` 仅申请预签名目标，实际 PUT 由调用方完成；`file upload` 独立走 API 直接上传，不调用 `pre-upload`。不要自行重用 `uploadUrl`。

直接上传目前使用识别场景。API-MOCK 记录了其他 scene 的服务端类型兼容问题，CLI 暂不开放切换；服务端业务错误原样返回，不自动改走预签名链路。

## 单枚识别

```bash
heribase identify --front-img <front-file-url> --back-img <back-file-url> --json
heribase identify detail --uri <identify-uri> --json
heribase identify list [--page <n>] [--page-size <n>] --json
```

`identify` 仅接受正反面都已上传且可访问的图片 URL。它返回识别记录 `uri`、标题、年份、铸记、估值、属性、正反面证据及以下只读资产关联：

```json
{
  "uri": "identify_1",
  "currencyNumber": "",
  "uniqUri": "",
  "userUniqUri": "user_coin_1"
}
```

- 当前 API 主动隐藏内部币种/版别标识，`currencyNumber` 和 `uniqUri` 可固定为空；不得恢复或猜测这些内部标识。其他身份字段为空表示未知；raw 响应必须保留原值，任务包规范化层将缺失身份字段表示为 JSON `null`，不要替换为猜测值。
- `userUniqUri` 表示用户的一枚具体实物，不等同于币种或版别；相同版别的多枚硬币可以拥有不同 `userUniqUri`。
- `identify detail` 额外保留 `isCollected`、`appraisalInfo` 和服务端扩展字段。不要仅凭同版别或相似图片自行合并为同一资产。

## 收藏读取与写入

```bash
heribase collection list [--page <n>] [--page-size <n>] --json
heribase collection detail --collection-uri <collection-uri> --json
heribase collection add --uri <identify-uri> --json
heribase collection cancel --collection-uri <collection-uri> --json
```

- `collection add` 使用识别记录的 `uri` 创建收藏；用户必须先确认准确条目数和范围。任务包工作流还必须校验 `collection/plan.json` 的当前授权摘要。
- `collection add` 只有在响应或后续只读核验取得真实 `collectionUri` 后才算成功；否则记录为 `reconcile_required`。
- `collection cancel` 只传 `collectionUri`。服务端自行回查并记录资产流水，Agent 不得传入资产关联字段。
- `collection add` 成功时返回 `collectionUri` 与服务端资产关联结果；`collection cancel` 成功时只需返回 `collectionUri`。

## 收藏编辑

```bash
heribase collection update --collection-uri <collection-uri> \
  [--years <year>] [--mint <mint>] [--price-grade <number>] \
  [--price-level <label>] [--value <number>] [--date-acquired <timestamp>] \
  [--collect-img <url>]... [--clear-collect-imgs] [--notes <text>] [--set-uri <uri>] \
  [--title <title>] [--custom-weight <text>] [--custom-size <text>] \
  [--custom-serial-number <text>] [--custom-denomination <text>] --json
```

- CLI 先查询 `collection edit-detail`，保留未修改的表单字段，再合并本次修改提交；读取失败或合并后仍缺编辑字段时不会继续写入；错误会列出缺失字段，需从服务端取得或由用户明确提供，不能猜空值。服务端没有版本锁，该流程不承诺与其他客户端并发编辑的原子性。
- `--collect-img` 最多可重复三次；`--clear-collect-imgs` 显式清空图片，二者不能同时使用。文本字段可传空字符串（例如 `--notes ""`、`--set-uri ""`）；省略表示保留原值。
- Agent 在编辑前必须取得完整编辑意图；不要为了更新一个字段而把未知字段作为空值覆盖。
- CLI 把 `--date-acquired` 映射到服务端历史字段 `dateAccquired`。
- 成功响应返回 `collectionUri` 和只读资产关联字段；不要用它们发起后续写入。

## 本地任务与 daemon

```bash
heribase task get <task-id> --json
heribase task list --json
heribase task wait <task-id> [--timeout <seconds>] --json
heribase task cancel <task-id> --json
heribase task retry <task-id> --json
heribase daemon <start|status> --json
heribase daemon stop [--force] --json
```

- `task wait` 最多等待指定秒数，默认由 CLI 决定；超时既不是成功也不是确定失败，应保留 `taskId` 并在任务包记录 `unknown/reconcile_required`，稍后只读查询。
- `task retry` 只恢复允许重试的读取/上传任务，以及从未开始执行的排队取消任务。识别、收藏写入、鉴定提交、追踪写入、收藏夹写入和引导创建没有服务端幂等合同；一旦执行失败或中断，不允许用 `task retry` 重放，应先核验结果，再在明确授权下建立新任务。
- `daemon stop --force` 会中断本地任务，仅在用户明确要求时调用。
- 对 `fetch failed`、连接拒绝或重置等本地通信错误，先运行 `daemon status`。仅当 daemon 已停止／异常，或 status 无法通信时，允许执行一次正常的 `daemon stop` 后 `daemon start`，再检查 status。不要以重启替代服务端错误排查，也不要在 daemon 健康时反复重启。
- 重启只恢复本地执行环境，不证明先前的写操作没有到达服务端。收藏写入出现不明确终态时必须先 `collection detail`、`collection list` 或任务查询核验，再决定是否可建立新的尝试。

## 本地历史检索

```bash
heribase history search --date <YYYY-MM-DD> [--query <text>] [--limit <n>] --json
```

- 该命令只查询本机 `~/.heribase/heribase.sqlite` 中的可重建历史派生表（旧 `history-index.sqlite` 在首次打开时一致性迁入，原文件保留），不创建任务，也不直接请求 HeriBase API。
- 索引从已完成且带服务端稳定账户 `uri`（本地映射为 `accountSubject`）的本地任务中提取任务时间、标题、年份、铸记、`identifyUri`、`collectionUri`、非空 `userCoinUri` 及批次上下文。`userCoinUri` 是用户拥有的具体实物标识，可区分同版别的多枚硬币；索引绝不保存币种 URI 或版别 URI。没有该账户标识的旧任务仍保留在任务 JSON 中，但不会参与跨会话历史搜索。
- `--date` 按运行 CLI 机器的本地日历日筛选；`--query` 匹配标题词项，`--limit` 默认为 20、最大为 100。
- 搜索结果只用于定位 URI。需要当前识别、价格或收藏状态时，必须继续调用 `identify detail` 或 `collection detail`；若远端返回不存在、无权限或已取消，不能将本地索引摘要展示为最新业务事实。

## 错误与确认

- 参数错误：修正输入后重新执行，不推断缺失正反面或 URI。
- `UNAUTHENTICATED`：要求用户登录。
- `API_ERROR` 保留 `businessCode`、`httpStatus`、`message` 和 `data`；额度错误的 `guide` 位于 `error.data.guide`，失败识别 URI 也从 `data` 读取。
- `INVALID_ARGUMENT` 为本地参数错误。`UNAUTHENTICATED` 要求重新登录。
- `DOWNSTREAM_UNAVAILABLE` 或网络错误：检查 `retryable`；`reconciliationRequired=true` 表示写入结果不确定，先只读核验，不能直接重试。HTTP 200 不代表业务成功，本地 task 完成一次 HTTP 调用也不代表真人鉴定报告已经完成。
- 添加、更新、取消收藏都是持久化写入。具体业务 Skill 应在调用前展示对象、数量、费用/额度与影响，并等待明确确认；任务包工作流还必须让确认绑定不可变计划摘要，执行前再次校验。


## 新增业务命令（2026-09-23）

以下全部支持 `--mode sync|async`（默认 sync）、`--json` 以及成对的 `--batch-id`/`--candidate-id`。同步输出仍是本地任务对象，业务内容位于 `result`；异步先返回 `taskId`，用 `task wait/get` 读取结果。配置的 `lang` 自动作为 `Accept-Language` 发送。

新增业务响应保留服务端扩展字段，包括 snake_case 的 `user_uniq_uri`。原有识别/收藏的 camelCase 别名继续兼容；各类资源 URI 必须结合 operation 使用，不能把鉴定或追踪 URI 传给识别详情。

### 识别资格与收藏夹

```bash
heribase identify eligibility --json
heribase collection capacity --json
heribase collection edit-detail --collection-uri <uri> --json
heribase collection sets list [--page <n>] [--page-size <n>] [--top-set-uri <uri>] --json
heribase collection sets create --name <name> [--is-coin 0|1] --json
heribase collection sets update --set-uri <uri> --set-name <name> --json
heribase collection sets delete --set-uri <uri> [--delete-content 0|1] --json
```

- `eligibility` 查询下一次识别资格，`allowed=false` 时读取 `limitStatus` 与 `guide`。查询结果不是额度预留，实际识别仍可能受限。
- `capacity` 是总收藏容量，不是每日额度。服务端仍在添加收藏时检查容量。
- `sets create` 的 `isCoin` 默认为 1。`sets delete` 默认 `deleteContent=0`，保留藏品并移出收藏夹；显式传 `1` 会连同内容一起删除，调用前必须明确用户授权范围。
- 把藏品移入收藏夹用 `collection update --collection-uri <uri> --set-uri <set-uri>`；移出用 `--set-uri ""`。
- 识别/基础收藏列表 `pageSize` 最大 100；收藏夹列表保留服务端页大小规则。

### 真人鉴定与次数购买

```bash
heribase appraisals experts --json
heribase appraisals products --json
heribase appraisals checkout --sku <sku> --version <n> --request-id <stable-id> \
  [--source-type identify|collection|tracking --source-uri <uri>] [--guide-uri <uri>] [--open] --json
heribase appraisals purchases pay --uri <purchase-uri> [--open] --json
heribase appraisals purchases detail --uri <purchase-uri> [--refresh 0|1] --json
heribase appraisals credits [--appraiser-type 0|1|5|10] [--appraiser-id <n>] --json
heribase appraisals submit --obverse-img <url> --reverse-img <url> --side-img <url> \
  [--more-img <url>]... [--video <url>] [--desc <text>] \
  [--collect-uri <uri> | --uri <identify-uri> | --tracking-uri <uri>] \
  [--appraiser-type 0|1|5|10] [--appraiser-id <n>] --json
heribase appraisals list [--page <n>] [--page-size <n>] [--keyword <text>] --json
heribase appraisals detail --uri <appraisal-uri> --json
```

`submit` 核销已有次数。先查次数并确认专家、图片和提交意图；三张主图的参数键必须提供，API 允许空字符串，建议都传有效图片。关联来源最多一个。鉴定进行中用 `list/detail` 查进度，不重复提交；本地 task completed 仅表示提交成功。

真人鉴定购买已接入，遵循以下顺序：

1. `experts` 完整保留 `officialList`、兼容对象 `official`、`recommendList`、`normalList`。新调用方使用 `officialList`：标准服务 `appraiserType=1/appraiserId=0` 为 7 天，加急 `5/0` 为 3 天；其他专家的时效直接使用服务端 `durationTime`，不套用官方时效。
2. `products` 是价格和可售状态的依据。用选中服务的 `purchaseFilter.appraiserType/appraiserId` 匹配商品 `entitlementSpec`，并确认 `productType=appraisal_credit`。金额按 `amount / 10^currencyExponent` 展示；商品为空或无匹配时不猜测 SKU。保留用户选定的 SKU 与 version。
3. 用户明确选择购买后执行 `checkout`。`requestId` 必须由调用方明确提供，同一次购买的重试使用原键、原参数；新购买使用新键。不得提交金额、币种、次数或期限。`sourceType/sourceUri` 可完全省略，但传入时必须成对。
4. 返回的 `paymentParameters` 原样交给网页支付流程。`checkout` 与 `purchases pay` 可加 `--open` 打开其中的 HTTP(S) `checkoutUrl`，仅限同步模式；异步任务完成后可根据原结果继续，或用订单 URI 执行 `purchases pay --open`。没有该键的 SDK 参数仍完整保留，需要网页支付组件处理，CLI 不拼造地址。浏览器打开失败会返回 `browser.opened=false` 和原因，同时保留订单结果，不重复下单。付款由用户在网页完成。
5. 用 `purchases detail --uri <原订单URI> --refresh 1` 触发验付。仅当 `paymentState=paid` 且 `fulfillmentState=granted` 时，派生 `purchaseConfirmed=true`；本地任务 completed、支付页跳转均不代表支付成功。已付款但尚未发放时继续查询原订单，不重新创建订单。订单标识接受至少 16 位字母数字，兼容 16 位历史订单及 PO 前缀的变长 Wpt 订单；原样使用服务端返回值，不截断或补齐长度。历史响应缺少上述状态字段时不推断已到账。
6. 再用 `credits --appraiser-type <所选类型> --appraiser-id <所选专家>` 确认匹配次数，准备图片，按已授权范围单独执行 `submit` 核销。官方服务传专家 ID `0`；指定专家传真实 ID。CLI 不因次数不足自动购买，也不会因购买成功自动提交鉴定。

`checkout` 网络失败可通过 `task retry` 重试原任务，保留原 `requestId`；`request_id_conflict` 等业务错误不可直接重试。鉴定 submit 的未知结果仍需先核对，不能重复核销。

支付 notify/return 是服务端及网页入口，不提供 CLI 模拟回调。付款返回后使用 `refresh=1` 主动验付，不能把返回网页视为已付款。会员与交易使用下述独立命令。

### 交易市场、买家与商家

```bash
heribase trade search --keyword Morgan --page 1 --page-num 20 --json
heribase trade categories --json
heribase trade goods detail --uri <商品URI> --json
heribase trade favorites list --page 1 --page-num 20 --json
heribase trade favorites add --uri <商品URI> --json
heribase trade favorites remove --uri <商品URI> --json
heribase trade addresses countries --scene address --json
heribase trade addresses list --page 1 --page-num 20 --json
heribase trade addresses detail --id <地址ID> --json
heribase trade orders preview --uri <商品URI> --address-id <地址ID> --json
heribase trade orders address --order-uri <原订单URI> --address-id <地址ID> --json
heribase trade orders create --uri <商品URI> --address-id <地址ID> --version <预下单版本> --pay-method 23 --open --json
heribase trade orders buy --state-type all --page 1 --page-num 20 --json
heribase trade orders sell --state-type underway --page 1 --page-num 20 --json
heribase trade orders detail --order-uri <订单URI> --json
heribase trade orders status --order-uri <订单URI> --json
heribase trade orders pay --order-uri <订单URI> --pay-method 23 --open --json
heribase trade orders cancel --order-uri <订单URI> --json
heribase trade orders logistics --order-uri <订单URI> --json
heribase trade orders receive --order-uri <订单URI> --json
heribase trade orders feedback --order-uri <订单URI> --json
heribase trade orders feedback-add --order-uri <订单URI> --content <问题说明> [--imgs <图片URL>] --json
```

网页支付采用 `wpt_center`，当前银行卡通道 `payMethod=23`；不是直接调用 Stripe 创建另一张交易单。预下单的 `goodsInfo/priceInfo/addressList` 是商品版本、运费、总价和地址的依据，确认后才执行 create。支付页缺失仍保留原订单，可用 pay 继续支付，不再创建订单。取消仅允许买家未付款订单；升级后的 Agent 接口必须返回相同 `orderUri` 与 `state=150` 才表示已关闭，旧接口单独的 `ret=success` 只表示日志上报。

地址新增／编辑使用 `trade addresses add|update`，传 `--street-address`、`--postal-code`、`--address-state`、`--city`、`--phone-number`、`--phone-country-code`、`--country-code` 和收件人 `--first-name/--last-name` 或 `--full-name`；编辑另传 `--id`。`delete|default --id` 分别删除或设置默认地址。

```bash
heribase trade seller eligibility --json
heribase trade seller goods list --type 1 --page 1 --page-num 20 --json
heribase trade seller goods detail --uri <商品URI> --json
heribase trade seller goods create --title <标题> --category 10 --imgs <图片URL> --sale-price 19.99 --postage 1.00 --json
heribase trade seller goods update --uri <商品URI> --title <标题> --category 10 --imgs <图片URL> --sale-price 19.99 --postage 1.00 --json
heribase trade seller goods up --uri <商品URI> --json
heribase trade seller goods down --uri <商品URI> --json
heribase trade seller goods delete --uri <商品URI> --json
heribase trade orders delivery-options --json
heribase trade orders deliver --order-uri <订单URI> --type 1 --logistics-company USPS --logistics-tracking-number <运单号> --delivery-certificate-imgs <凭证URL> --json
heribase trade seller account --json
heribase trade seller bills --page 1 --page-num 20 --json
heribase trade seller bill --id <账单ID> --json
heribase trade seller withdrawal-info --json
heribase trade seller paypal --paypal-name <收款人> --paypal-email <邮箱> --json
heribase trade seller withdraw --paypal-name <收款人> --paypal-email <邮箱> --money 1025 --json
```

`type=1/2` 的商品列表分别是在售／下架；发布 category 为硬币 `10`、纸币 `20`。发布和编辑支持 `--description`、`--is-global-shipping 1 --global-postage <运费>` 及已有收藏／识别／鉴定来源。商品价格和运费使用 USD 主单位，**提现的 money 使用整数美分**（1025 = $10.25），不可混用。图片参数可重复提供，先用 `file upload` 得到服务图片地址。卖家发布资格返回 `waitDeliveryOrderUri` 时先处理该订单。

交易写入没有通用幂等键，未知结果不能自动重放。查看原 CLI 任务、订单状态及工作台执行证据；明确失败后重新核对范围。买卖身份与状态由服务端校验，切换页面不会获得另一角色权限。

地址新增／编辑支持 `--additional-address-info`，用于保留公寓、楼层等补充信息。Agent 商品更新省略的专业资料、原鉴定关联与国家字段由后端保留；关闭国际配送时 `globalPostage=0` 合法，开启时仍为 10–200 USD。已付款的待补地址订单只能在配送范围和原订单运费匹配后确认；同一订单和地址的重试沿用冻结快照。

### Wpt 会员与优惠

```bash
heribase subscriptions current --json
heribase memberships products --json
heribase memberships checkout --sku <服务端SKU> --version <商品版本> --request-id <本次购买唯一键> --open --json
heribase memberships purchases pay --uri <32位订单URI> --open --json
heribase memberships purchases detail --uri <32位订单URI> --refresh 1 --json
heribase purchases list --page 1 --page-size 20 --json
heribase purchases entitlements --json
```

会员商品为 Wpt 单次购买：标准周／月／年固定期，3 天免费试用和首月优惠由服务端商品及资格决定；不会自动续费。网页不得提交金额、优惠比例或期限。`eligible=false` 时展示 `eligibilityReason`；有 `existingPurchaseUri` 则继续检查原优惠订单。免费试用 `amount=0`、`paymentRequired=false`，无需打开支付页面；服务端唯一领取记录控制一次资格。首月优惠只授予一个月，后续 `followupProduct` 展示当前标准年卡价格，续购另行确认。

同一次 checkout 的重试必须沿用原 `requestId`、SKU 和 version，防止多建订单。支付成功与权益发放分开读取；普通付费订单需 `paymentState=paid` 且 `fulfillmentState=granted` 才确认到账。免费试用需 `paymentRequired=false` 且权益已发放。当前会员有效期和已有次数读 `purchases entitlements`，原会员权益说明读 `subscriptions current`。

### 钱币追踪

```bash
heribase tracking products --json
heribase tracking slots --json
heribase tracking checkout --sku <server-sku> --version <n> --request-id <stable-id> [--source-type collection --source-uri <collection-uri>] --open --json
heribase tracking purchases pay --uri <订单URI> [--open] --json
heribase tracking purchases detail --uri <订单URI> --refresh 1 --json
heribase tracking search [--keyword <text>] [--exclude-uniq-uris <existing-filter>] [--page <n>] [--page-size <n>] --json
heribase tracking add --collect-uri <collection-uri> --json
heribase tracking add --tracking-uri <tracking-uri> --json
heribase tracking list [--page <n>] [--page-size <n>] --json
heribase tracking detail --uri <tracking-uri> --json
heribase tracking update --uri <tracking-uri> --grade <0-70> --label <text> --json
```

`products` 查询服务端当前可购买的 Wpt 追踪位商品；商品 SKU、版本、价格和次数以此目录为准。`checkout` 复用相同的 Wpt 支付和追踪位履约流程，金额与次数不由调用方提交；重试同一订单必须沿用原 `request-id`、SKU 和 version。`purchases pay` 只恢复已有订单支付页，`purchases detail --refresh 1` 主动验付和履约；只有 `paymentState=paid` 且 `fulfillmentState=granted` 才代表追踪位已到账。`search --exclude-uniq-uris` 仅透传已有的只读排除过滤值，不构造内部 ID，不把它作为写入资产标识。`add` 使用本人收藏新增追踪，或使用 trackingUri 续期，可能消耗已有追踪位；不接受裸内部版别 URI 或交易来源。`update` 同时提供品相和标签，标签最多 32 字符，允许 `--label ""` 清空。

### Daily Coin

```bash
heribase daily home --json
heribase daily list [--page <n>] [--page-size <1-20>] --json
heribase daily detail --id <positive-integer> --json
```

文章正文保留 HTML。`isLocked=1` 且 `content=""` 是会员锁定，不是读取失败；需要引导时显式执行 `app-guide create --reason subscription`，不自动购买或生成正文。

### App 引导与价格

```bash
heribase app-guide create --reason <reason> [--source-type identify|collection|tracking --source-uri <uri>] --json
heribase prices live --source-type identify|collection|tracking --source-uri <uri> --json
heribase prices trends --source-type identify|collection|tracking --source-uri <uri> --json
```

`reason`：`identify_limit`、`collection_limit`、`live_price`、`price_trends`、`subscription`、`tracking`。来源类型和 URI 必须成对。

非会员可能只取得 App 引导；服务端返回真实价格或序列时完整保留。CLI 不根据本地推测过滤会员数据，也不生成 API 未返回的价格序列。识别参考估价与实时价格不同。

`guideUrl` 可能是相对于配置 API origin 的路径，由调用方按 URL 规则解析；`guideUri` 只传播不解析。不提供支付通知、浏览器返回、App 激活/承接/转化上报命令，不模拟真实点击。

### 分页

新列表保留原始 `page` / `isEnd` 和 `list` 或 `items`，并添加 `pagination.currentPage`（本次请求页）与 `pagination.nextPage`（下一页，结束时为 null）。收藏夹、鉴定记录、Daily Coin 的原始 `page` 是下一页；追踪的原始 `page` 是当前页。优先使用 `pagination.nextPage`，避免漏页。CLI 不自动遍历全量记录。
