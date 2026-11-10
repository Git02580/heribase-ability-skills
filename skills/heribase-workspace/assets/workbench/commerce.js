import { esc, href, link, tag, empty } from './views.js';

export const commercePages = new Set(['market', 'buying', 'selling', 'membership']);
const pageTitles = { market: '交易市场', buying: '我的购买', selling: '商家管理', membership: '会员订阅' };
const orderStates = { 100: '等待支付', 105: '待补全地址', 110: '等待发货', 120: '等待收货', 130: '售后处理中', 140: '交易完成', 150: '订单已关闭' };
const payStates = { unpaid: '等待支付', paid: '已付款', failed: '支付失败', closed: '已关闭', refunded: '已退款' };
const fulfillmentStates = { pending: '待发放', granted: '权益已到账', failed: '发放待处理' };
const actionButton = (label, action, data = {}, style = 'quiet') =>
  `<button type="button" class="button ${style}" data-action="commerce-${action}" ${Object.entries(data)
    .map(([key, value]) => `data-${key}="${esc(value)}"`)
    .join(' ')}>${esc(label)}</button>`;
const url = (value) => {
  try {
    const parsed = new URL(value);
    return ['https:', 'http:'].includes(parsed.protocol) && !parsed.username && !parsed.password ? parsed.href : '';
  } catch {
    return '';
  }
};
const picture = (value, title = '') =>
  url(value) ? `<img src="${esc(url(value))}" alt="${esc(title)}" loading="lazy">` : '<div class="commerce-no-image">暂无图片</div>';
const majorPrice = (value) =>
  value === null || value === undefined || value === '' ? '价格待查询' : `${/[A-Za-z$€£¥]/.test(String(value)) ? '' : '$'}${esc(value)}`;
const minorPrice = (product) => {
  if (!Number.isSafeInteger(product?.amount) || !Number.isInteger(product?.currencyExponent) || !product?.currency) return '价格待查询';
  try {
    return new Intl.NumberFormat('zh-CN', { style: 'currency', currency: product.currency.toUpperCase() }).format(
      product.amount / 10 ** product.currencyExponent,
    );
  } catch {
    return '价格待查询';
  }
};
const period = (product) => {
  const spec = product?.entitlementSpec || {};
  const unit = { day: '天', week: '周', month: '个月', year: '年' }[spec.durationUnit];
  return unit && Number.isInteger(spec.durationCount) ? `${spec.durationCount} ${unit}` : '期限待查询';
};
const isTrial = (product) => product?.entitlementSpec?.offerType === 'trial' && product.amount === 0;
const offerTitle = (product) =>
  isTrial(product)
    ? `${period(product)}免费试用`
    : product?.entitlementSpec?.offerType === 'introductory'
      ? product.entitlementSpec.durationUnit === 'month' && product.entitlementSpec.durationCount === 1
        ? '首月优惠'
        : '首次优惠'
      : `${period(product)}会员`;
const offerReason = (product) =>
  ({
    membership_offer_used: '已使用过此类优惠，可选择标准会员。',
    membership_auto_renew_active: '当前已有生效中的自动续费会员。请先在原购买渠道管理续费，再购买固定期限会员。',
    membership_offer_pending: '已有优惠订单，请先处理原订单。',
    membership_new_user_only: '此优惠仅限符合条件的新会员。',
  })[product.eligibilityReason] || '当前账户暂不符合此优惠的领取条件。';
const followupText = (product) =>
  product.followupProduct
    ? `<p class="muted">到期后可另行购买 ${esc(period(product.followupProduct))}会员，当前价格 ${esc(minorPrice(product.followupProduct))}。续购需再次确认，不会自动扣款。</p>`
    : '<p class="muted">到期后可在这里另行选择会员期限，不会自动续费。</p>';
const addressText = (value) =>
  [
    value?.fullName || [value?.firstName, value?.lastName].filter(Boolean).join(' '),
    value?.streetAddress,
    value?.additionalAddressInfo,
    value?.city,
    value?.addressState,
    value?.postalCode,
    value?.countryName || value?.countryCode,
    value?.phoneNumber,
  ]
    .filter(Boolean)
    .join(' · ');
const pairs = (values) =>
  `<dl class="commerce-facts">${values
    .filter(([, value]) => value !== undefined && value !== null && value !== '')
    .map(([label, value]) => `<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`)
    .join('')}</dl>`;
const fieldNames = {
  title: '标题',
  description: '说明',
  salePrice: '售价（USD）',
  postage: '境内运费（USD）',
  globalPostage: '国际运费（USD）',
  fullName: '收件人',
  firstName: '名字',
  lastName: '姓氏',
  streetAddress: '街道地址',
  additionalAddressInfo: '补充地址（公寓／楼层等）',
  postalCode: '邮政编码',
  addressState: '州／省',
  city: '城市',
  phoneNumber: '联系电话',
  phoneCountryCode: '电话区号',
  countryCode: '国家代码',
  content: '反馈内容',
  logisticsCompany: '物流公司',
  logisticsTrackingNumber: '物流单号',
  email: '通知邮箱',
  paypalName: '收款人姓名',
  paypalEmail: 'PayPal 邮箱',
  money: '提现金额（USD）',
};

export function commerceSummary(summary) {
  return `${summary.goods ? `<h3>${esc(summary.goods.title || '商品')}</h3>` : ''}
    ${
      summary.price
        ? pairs([
            ['商品金额', summary.price.salePrice],
            ['运费', summary.price.postage],
            ['实付合计（USD）', summary.price.totalPrice],
          ])
        : ''
    }
    ${summary.address ? `<h3>收货地址</h3><p>${esc(addressText(summary.address))}</p>` : ''}
    ${
      summary.product
        ? `<h3>${esc(offerTitle(summary.product))}</h3>${pairs([
            ['本次支付', isTrial(summary.product) ? '免费 · 无需付款' : minorPrice(summary.product)],
            ['本次有效期限', period(summary.product)],
          ])}${followupText(summary.product)}`
        : ''
    }
    ${
      summary.orderUri
        ? pairs([
            ['交易订单', summary.orderUri],
            ['当前状态', orderStates[summary.orderState] || '待查询'],
          ])
        : ''
    }
    ${
      summary.changes
        ? pairs(
            Object.entries(summary.changes)
              .filter(([key]) => fieldNames[key])
              .map(([key, value]) => [fieldNames[key], value]),
          )
        : ''
    }
    ${summary.changes?.imgs ? `<div class="commerce-thumbnails">${summary.changes.imgs.map((src) => picture(src, '商品照片')).join('')}</div>` : ''}
    ${summary.changes?.deliveryCertificateImgs ? `<div class="commerce-thumbnails">${summary.changes.deliveryCertificateImgs.map((src) => picture(src, '发货凭证')).join('')}</div>` : ''}`;
}

function goodsCards(list, seller = false, type = 1) {
  return list.length
    ? `<div class="commerce-grid">${list
        .map(
          (goods) => `<article class="panel commerce-card">
    <a class="commerce-cover" href="${esc(href('market', null, goods.uri))}">${picture(goods.coverImg, goods.title)}</a>
    <div class="commerce-card-body"><small>${esc(goods.sellerInfo?.nickname || goods.underText || '')}</small><h3>${esc(goods.title)}</h3>
    <div class="commerce-price">${majorPrice(goods.salePrice)}</div><p class="muted">运费 ${majorPrice(goods.postage)}</p>
    <div class="actions">${seller ? `${actionButton('编辑', 'goods-edit', { id: goods.uri })}${actionButton(type === 1 ? '下架' : '上架', 'goods-state', { id: goods.uri, change: type === 1 ? 'down' : 'up' })}${type === 2 ? actionButton('删除', 'goods-state', { id: goods.uri, change: 'delete' }, 'danger') : ''}` : link('查看商品', 'market', null, goods.uri, 'button small primary')}</div></div></article>`,
        )
        .join('')}</div>`
    : empty('暂无商品', '可以调整筛选条件，或稍后刷新。');
}

function orderRows(list, page) {
  return list.length
    ? `<div class="table-wrap"><table><thead><tr><th>商品与订单</th><th>状态</th><th>订单金额</th><th></th></tr></thead><tbody>${list.map((order) => `<tr><td><div class="commerce-order-title">${picture(order.goodsInfo?.coverImg)}<div><strong>${esc(order.goodsInfo?.title || order.uri)}</strong><small>${esc(order.uri)}</small></div></div></td><td>${tag(order.orderStateText || orderStates[order.orderState] || '状态待查询')}</td><td>${majorPrice(order.totalPrice)}</td><td>${link('查看订单', page, null, order.uri, 'button small')}</td></tr>`).join('')}</tbody></table></div>`
    : empty('暂无订单', page === 'buying' ? '从交易市场挑选钱币，购买后的订单会显示在这里。' : '买家下单后，可在这里查看支付与发货状态。');
}

function orderDetail(detail, id) {
  const state = detail.stateDetail || {},
    seller = detail.isSeller === true;
  const goods = detail.goodsInfo || {};
  return `<div class="two-col"><article class="panel pad"><div class="commerce-detail-cover">${picture(goods.coverImg, goods.title)}</div><h2>${esc(goods.title)}</h2>
    ${pairs([
      ['商品金额（USD）', goods.salePrice],
      ['运费（USD）', goods.postage],
      ['订单金额（USD）', goods.totalPrice],
      ['实付（USD）', goods.paidPrice],
    ])}
    <h3>收货地址</h3><p>${esc(addressText(detail.address))}</p><h3>物流与支付</h3>
    ${pairs([
      ['订单编号', id],
      ['支付时间', detail.payInfo?.payTime],
      ['发货时间', detail.payInfo?.sellerDeliveryTime],
      ['收货时间', detail.payInfo?.confirmTime],
      ['物流公司', detail.deliveryInfo?.logisticsCompany],
      ['物流单号', detail.deliveryInfo?.logisticsTrackingNumber],
    ])}
    ${actionButton('查看物流', 'logistics', { id })} ${actionButton('查看反馈', 'feedback-detail', { id })}</article>
    <aside class="panel pad"><div class="eyebrow">${seller ? 'SELLER ORDER' : 'MY PURCHASE'}</div><h2>${esc(state.orderStatus || orderStates[state.state] || '状态待查询')}</h2><p>${esc(state.orderDescription || '')}</p><div class="actions">
    ${!seller && state.state === 100 ? actionButton('继续支付', 'order-pay', { id }, 'primary') : ''}
    ${!seller && state.state === 100 ? actionButton('取消未付款订单', 'order-cancel', { id }, 'danger') : ''}
    ${!seller && state.state === 105 ? actionButton(detail.address?.id ? '继续确认原地址' : '补全收货地址', 'order-address', { id, ...(detail.address?.id ? { 'address-id': detail.address.id } : {}) }, 'primary') : ''}
    ${!seller && state.state === 120 ? actionButton('确认收货', 'order-receive', { id }, 'primary') : ''}
    ${seller && state.canShip ? actionButton('填写发货信息', 'order-deliver', { id }, 'primary') : ''}
    ${[110, 120, 130, 140].includes(state.state) ? actionButton('反馈订单问题', 'feedback', { id }) : ''}
    ${actionButton('刷新订单状态', 'refresh')}</div></aside></div>`;
}

function membershipPage(data) {
  const member = data.entitlements?.membership || {};
  const products = data.catalog?.products || [];
  const orders = (data.purchases?.list || []).filter((order) => order.product?.productType === 'membership');
  const now = Date.now();
  const formatTime = (value) => {
    const timestamp = Number(value);
    return Number.isFinite(timestamp) && timestamp > 0 ? new Date(timestamp).toLocaleString('zh-CN') : '';
  };
  const currentEnd = member.active === true && Number(member.endTimeMs) > now ? Number(member.endTimeMs) : 0;
  // 服务端会员订单时间戳为秒；只把已付款且权益已到账、尚未到期的订单加入汇总。
  const validMembershipOrders = orders
    .filter((order) => order.paymentState === 'paid' && order.fulfillmentState === 'granted' && Number(order.periodEnd) * 1000 > now)
    .sort((left, right) => Number(left.periodStart || 0) - Number(right.periodStart || 0));
  const latestEnd = Math.max(currentEnd, ...validMembershipOrders.map((order) => Number(order.periodEnd) * 1000));
  const hasMembership = member.active === true || validMembershipOrders.length > 0;
  const currentEntitlementDetail = currentEnd
    ? `<p class="muted">当前服务端权益：有效至 ${esc(formatTime(currentEnd))}</p>`
    : '';
  const membershipDetails = validMembershipOrders.length
    ? `<section class="membership-details"><div class="membership-details-heading"><h2>有效会员产品明细</h2><span class="muted">${validMembershipOrders.length} 项</span></div><div class="membership-entitlement-list">${validMembershipOrders
        .map((order) => {
          const product = order.product || {};
          const startsAt = Number(order.periodStart) > 0 ? Number(order.periodStart) * 1000 : 0;
          const scheduled = startsAt > now;
          return `<article class="membership-entitlement"><div class="membership-card-head"><div><h3>${esc(offerTitle(product))}</h3><small>${esc(product.sku || '会员产品')}</small></div>${tag(scheduled ? '已排期' : '生效中', scheduled ? 'amber' : 'green')}</div>
            <div class="membership-card-price"><strong>${esc(minorPrice(order))}</strong><span>${esc(period(product))}</span></div>
            <div class="membership-card-period"><div><small>权益开始</small><strong>${esc(formatTime(startsAt) || '待查询')}</strong></div><span aria-hidden="true">→</span><div><small>权益到期</small><strong>${esc(formatTime(Number(order.periodEnd) * 1000) || '待查询')}</strong></div></div>
            <div class="membership-card-footer"><span>已付款 · 权益已到账</span><small title="${esc(order.uri || '')}">订单 ${esc(order.uri || '编号待查询')}</small></div></article>`;
        })
        .join('')}</div></section>`
    : '';
  return `<div class="note neutral"><strong>${hasMembership ? '会员权益生效中' : '当前未开通会员'}</strong><p>${latestEnd ? `汇总有效期至 ${esc(formatTime(latestEnd))}` : hasMembership ? '会员权益有效，服务端未提供到期时间。' : '选择适合你的使用期限，支付完成后在这里查询权益。'}</p>${currentEntitlementDetail}</div>
    ${membershipDetails}
    ${data.subscription?.error ? `<p role="status" class="muted">权益说明查询失败：${esc(data.subscription.error)}。可刷新重试。</p>` : ''}
    ${data.subscription?.benefitsList?.length ? `<section class="panel pad"><h2>当前会员权益</h2><ul>${data.subscription.benefitsList.map((benefit) => `<li>${esc(benefit.title)}</li>`).join('')}</ul></section>` : ''}
    <div class="commerce-grid commerce-plans">${products
      .map(
        (
          product,
        ) => `<article class="panel pad"><div class="eyebrow">MEMBERSHIP</div><h2>${esc(offerTitle(product))}</h2><div class="commerce-price">${isTrial(product) ? '免费' : esc(minorPrice(product))}</div>
    <p>${isTrial(product) ? '无需付款 · 每位符合条件的用户限领一次' : `本次获得 ${esc(period(product))}会员`}</p>${followupText(product)}
    ${product.eligible === false ? `<p>${esc(offerReason(product))}</p>${product.existingPurchaseUri ? actionButton('查看原优惠订单', 'membership-detail', { id: product.existingPurchaseUri }) : ''}` : actionButton(isTrial(product) ? '查看并领取试用' : '查看并确认购买', 'membership-buy', { sku: product.sku }, 'primary')}</article>`,
      )
      .join('')}</div>
    ${products.length ? '' : empty('暂无可购买会员商品', '服务端尚未返回可售商品，请稍后刷新。')}
    <h2>会员购买记录</h2>${orders.length ? orders.map((order) => `<article class="panel pad commerce-purchase"><div><h3>${esc(offerTitle(order.product))} · ${esc(minorPrice(order))}</h3><p>${order.paymentRequired === false ? '无需付款' : esc(payStates[order.paymentState] || order.paymentState)} · ${esc(fulfillmentStates[order.fulfillmentState] || order.fulfillmentState)}</p><small class="muted">${esc(order.uri)}</small></div><div class="actions">${order.paymentState === 'unpaid' ? actionButton('继续支付', 'membership-pay', { id: order.uri }) : ''}${actionButton('检查订单与到账', 'membership-detail', { id: order.uri })}</div></article>`).join('') : '<p class="muted">本页没有会员购买记录。</p>'}`;
}

const recoveryActions = (entry) => {
  const data = entry.data;
  const member = data.action === 'memberships.checkout' && ['failed', 'reconcile_required'].includes(data.status);
  return `${['reconcile_required', 'running'].includes(data.status) ? actionButton('核验原任务', 'recover', { id: entry.id }) : ''}${member ? actionButton('继续原会员请求', 'resume-membership', { id: entry.id }) : data.status === 'failed' ? actionButton('重新检查并确认', 'replan', { id: entry.id }) : ''}`;
};

function historyRows(operations) {
  return operations?.length
    ? operations
        .map(
          (entry) =>
            `<article class="panel pad commerce-purchase"><div><h3>${esc(entry.data.label)}</h3><p>${esc(entry.data.message)}</p><small>${esc(entry.updatedAt || '')}</small></div><div>${tag({ completed: '已完成', failed: '明确失败', reconcile_required: '待核验', running: '执行中' }[entry.data.status] || entry.data.status)}${recoveryActions(entry)}${relatedOrder(entry.data)}</div></article>`,
        )
        .join('')
    : empty('暂无执行记录', '本机发起的交易操作会在这里保留执行结果。');
}

function relatedOrder(operation) {
  const orderUri = operation.result?.orderUri || operation.params?.orderUri;
  if (orderUri) return link('查看原订单', operation.scope?.isSeller ? 'selling' : 'buying', null, orderUri, 'button small');
  // 下单未返回订单编号时提供当前账户订单入口，不能猜测并绑定最近一条订单。
  if (operation.action === 'trade.orders.create') return link('核对买入订单', 'buying', null, null, 'button small');
  if (operation.action?.startsWith('memberships.')) return link('核对会员订单', 'membership', null, null, 'button small');
  return '';
}

export function renderCommercePage(route, state = {}) {
  const { page, item } = route,
    data = state.data || {},
    tab = state.tab || (page === 'selling' ? 'goods' : 'orders');
  const navigation = `<nav class="commerce-nav" aria-label="交易与会员">${Object.entries(pageTitles)
    .map(([key, title]) => `<a class="${key === page ? 'active' : ''}" href="${href(key)}">${title}</a>`)
    .join('')}</nav>`;
  const title = `<div class="page-head"><div><div class="eyebrow">${page === 'membership' ? 'MEMBERSHIP' : 'COIN MARKET'}</div><h1>${pageTitles[page]}</h1><p>${page === 'selling' ? '管理自己的商品、订单与收款。' : page === 'buying' ? '查看购买进度、管理收货地址和处理订单问题。' : page === 'membership' ? '选择会员期限，查看支付与权益到账状态。' : '浏览在售钱币，查看实物图片和卖家信息。'}</p></div>${actionButton('刷新', 'refresh')}</div>${navigation}`;
  if (state.loading) return `${title}<div class="empty-state" role="status">正在读取最新数据…</div>`;
  if (state.error) return `${title}<div class="note warning" role="alert"><p>${esc(state.error)}</p>${actionButton('重新加载', 'refresh')}</div>`;
  if (page === 'membership')
    return (
      title +
      membershipPage(data) +
      pagination(data.purchases || {}, state) +
      '<h2>本机会员执行记录</h2>' +
      historyRows((data.operations || []).filter((entry) => entry.data.action?.startsWith('memberships.')))
    );
  if (page === 'market' && item)
    return `${title}${link('← 返回市场', 'market', null, null, 'text-link')}<div class="two-col"><article class="panel pad"><div class="commerce-gallery">${(data.imageList || [data.coverImg]).map((src) => picture(src, data.title)).join('')}</div><h2>${esc(data.title)}</h2><p class="commerce-description">${esc(data.description)}</p></article><aside class="panel pad"><div class="commerce-price">${majorPrice(data.salePrice)}</div><p>参考运费 ${majorPrice(data.postage)}，按收货地址结算。</p>${pairs(
      [
        ['卖家', data.sellerInfo?.nickname],
        ['所在地', data.goodsAddress],
      ],
    )}<div class="actions">${!data.isOwner && data.saleState === 1 ? actionButton('选择地址并购买', 'buy', { id: item }, 'primary') : tag(data.isOwner ? '这是你的商品' : '当前不可购买')}${actionButton(data.isFavorite ? '取消关注' : '关注商品', 'favorite', { id: item, change: data.isFavorite ? 'remove' : 'add' })}</div></aside></div>`;
  if (item) return `${title}${link('← 返回列表', page, null, null, 'text-link')}${orderDetail(data, item)}`;
  if (page === 'market')
    return `${title}<form data-commerce-form="search" class="commerce-toolbar"><label>搜索商品<input name="keyword" value="${esc(state.keyword || '')}" placeholder="钱币名称、年份或关键词"></label><button class="button primary" type="submit">搜索</button></form>${goodsCards(data.list || [])}${pagination(data, state)}`;
  const tabs =
    page === 'selling'
      ? { goods: '商品管理', orders: '卖出订单', account: '资金与收款', history: '执行记录' }
      : { orders: '买入订单', addresses: '收货地址', favorites: '关注商品', history: '执行记录' };
  const tabBar = `<div class="commerce-tabs">${Object.entries(tabs)
    .map(([id, label]) => actionButton(label, 'tab', { tab: id }, tab === id ? 'primary' : 'quiet'))
    .join('')}</div>`;
  if (tab === 'history') return title + tabBar + historyRows(data.operations);
  if (tab === 'favorites') return title + tabBar + goodsCards(data.list || []) + pagination(data, state);
  if (tab === 'addresses')
    return `${title}${tabBar}<p>${actionButton('＋ 新增地址', 'address-edit', {}, 'primary')}</p>${(data.list || []).map((address) => `<article class="panel pad commerce-purchase"><div><h3>${esc(address.fullName)}</h3><p>${esc(addressText(address))}</p>${address.state === 2 ? tag('默认地址') : ''}</div><div class="actions">${actionButton('编辑', 'address-edit', { id: address.id })}${actionButton('设为默认', 'address-default', { id: address.id })}${actionButton('删除', 'address-delete', { id: address.id }, 'danger')}</div></article>`).join('') || empty('还没有收货地址', '购买前请添加真实收件地址。')}${pagination(data, state)}`;
  if (tab === 'goods')
    return `${title}${tabBar}<div class="commerce-toolbar">${actionButton('＋ 发布商品', 'goods-edit', {}, 'primary')}${actionButton('在售', 'goods-filter', { type: 1 }, state.goodsType !== 2 ? 'primary' : 'quiet')}${actionButton('已下架', 'goods-filter', { type: 2 }, state.goodsType === 2 ? 'primary' : 'quiet')}</div>${goodsCards(data.list || [], true, state.goodsType || 1)}${pagination(data, state)}`;
  if (tab === 'account')
    return `${title}${tabBar}<article class="panel pad"><h2>资金与收款</h2>${pairs([
      ['可提现余额', data.account?.balance],
      ['待结算金额', data.account?.waitSettleBalance],
      ['PayPal 收款人', data.withdrawal?.paypalName],
      ['PayPal 邮箱', data.withdrawal?.paypalEmail],
    ])}<div class="actions">${actionButton('设置收款账户', 'paypal-edit')}${actionButton('申请提现', 'withdraw')}</div></article><h2>资金账单</h2>${(data.bills?.list || []).map((bill) => `<article class="panel pad commerce-purchase"><div><h3>${esc(bill.title)}</h3><p>${esc(bill.subTitle || bill.desc)}</p><small>${esc(bill.time)}</small></div><strong>${majorPrice(bill.money)}</strong></article>`).join('') || '<p class="muted">暂无账单。</p>'}${pagination(data.bills || {}, state)}`;
  return `${title}${tabBar}<div class="commerce-toolbar">${[
    ['all', '全部'],
    ['underway', '进行中'],
    ['finish', '已结束'],
  ]
    .map(([id, label]) => actionButton(label, 'orders-filter', { filter: id }, (state.orderFilter || 'all') === id ? 'primary' : 'quiet'))
    .join('')}</div>${orderRows(data.list || [], page)}${pagination(data, state)}`;
}

function pagination(data, state) {
  const page = state.pageNumber || 1;
  const hasNext = data.isEnd === false || (data.isEnd === undefined && data.list?.length === 20);
  return `<div class="commerce-pagination">${page > 1 ? actionButton('上一页', 'page', { page: page - 1 }) : ''}<span>第 ${page} 页</span>${hasNext ? actionButton('下一页', 'page', { page: page + 1 }) : ''}</div>`;
}

const input = (key, value = '', required = true, type = 'text') =>
  `<label>${esc(fieldNames[key] || key)}<input name="${key}" value="${esc(value)}" type="${type}" ${required ? 'required' : ''} ${type === 'number' ? 'step="0.01" min="0"' : ''}></label>`;
const textarea = (key, value = '', label) => `<label>${esc(label || fieldNames[key] || key)}<textarea name="${key}" rows="4">${esc(value)}</textarea></label>`;
const formValues = (form) => Object.fromEntries(new FormData(form));
const photoList = (key, images) =>
  images
    .map(
      (src, index) =>
        `<figure>${picture(src, `照片 ${index + 1}`)}<figcaption>${actionButton('移除', 'photo-remove', { field: key, index }, 'small')}</figcaption></figure>`,
    )
    .join('');
const photoField = (key, images, label) =>
  `<fieldset class="commerce-photo-field"><legend>${esc(label)}</legend><input type="hidden" name="${key}" value="${esc(images.join('\n'))}"><div class="commerce-thumbnails" data-commerce-photos="${key}">${photoList(key, images)}</div><label class="button quiet">从本地选择照片<input type="file" data-commerce-upload="${key}" multiple accept="image/jpeg,image/png,image/webp"></label><p class="muted" data-commerce-upload-status="${key}" aria-live="polite">最多 9 张，每张不超过 20 MiB；支持 JPG、PNG、WebP。</p></fieldset>`;

export function createCommerceController({ request, dialog, redraw, toast, setDirty }) {
  const state = { key: null, loaded: null, loading: false, data: null, tab: null, pageNumber: 1, keyword: '' };
  let currentRoute = {},
    generation = 0,
    pendingPlan = null,
    confirmationId = null,
    editing = null,
    pendingResumeId = null;
  // 外部支付页关闭后，浏览器会将焦点还给工作台；只在这一时机查一次原订单，
  // 不启动后台轮询，也不根据支付商的浏览器跳转自行推断付款成功。
  let pendingTradePaymentUri = null,
    lastPaymentReturnCheck = 0;
  const uploading = new WeakSet();
  const query = (action, params = {}) => request('/api/commerce/query', { action, params });
  const render = (route) => renderCommercePage(route, state);
  const routeKey = (route) => JSON.stringify([route.page, route.item]);
  async function load(route, force = false) {
    const key = routeKey(route);
    if (state.key !== key) {
      generation += 1;
      state.loading = false;
      state.key = key;
      state.loaded = null;
      state.error = null;
      state.pageNumber = 1;
      if (currentRoute.page !== route.page) state.tab = null;
    }
    currentRoute = route;
    if (!force && (state.loaded === key || state.loading)) return;
    const sequence = ++generation;
    state.loading = true;
    state.error = null;
    if (force) redraw();
    try {
      const paging = { page: state.pageNumber, pageNum: 20 };
      let data;
      if (route.page === 'market')
        data = await query(route.item ? 'trade.goods.detail' : 'trade.search', route.item ? { uri: route.item } : { ...paging, keyword: state.keyword });
      else if (route.page === 'membership') {
        const [catalog, entitlements, purchases, subscription, history] = await Promise.all([
          query('memberships.products'),
          query('purchases.entitlements'),
          query('purchases.list', { page: state.pageNumber, pageSize: 20 }),
          // 权益说明来自既有 App 合同；失败单独展示，不抹掉已核实的购买记录和余额。
          query('subscriptions.current').catch((error) => ({ error: error.message })),
          request('/api/commerce/history', {}),
        ]);
        data = { catalog, entitlements, purchases, subscription, operations: history.operations };
      } else if (route.item) data = await query('trade.orders.detail', { orderUri: route.item });
      else {
        const tab = state.tab || (route.page === 'selling' ? 'goods' : 'orders');
        if (tab === 'history') data = await request('/api/commerce/history', {});
        else if (tab === 'orders')
          data = await query(route.page === 'selling' ? 'trade.orders.sell' : 'trade.orders.buy', { ...paging, stateType: state.orderFilter || 'all' });
        else if (tab === 'goods') data = await query('trade.seller.goods.list', { ...paging, type: state.goodsType || 1 });
        else if (tab === 'addresses') data = await query('trade.addresses.list', paging);
        else if (tab === 'favorites') data = await query('trade.favorites.list', paging);
        else if (tab === 'account') {
          const [account, bills, withdrawal] = await Promise.all([
            query('trade.seller.account'),
            query('trade.seller.bills', paging),
            query('trade.seller.withdrawal-info'),
          ]);
          data = { account, bills, withdrawal };
        }
      }
      // 市场搜索、角色切换与订单跳转的慢响应不能覆盖较新的页面。
      if (sequence !== generation || key !== state.key) return;
      state.data = data;
      state.loaded = key;
    } catch (error) {
      if (sequence === generation && key === state.key) {
        state.error = error.message;
        state.loaded = key;
      }
    } finally {
      if (sequence === generation) {
        state.loading = false;
        redraw();
      }
    }
  }
  async function preview(action, params) {
    confirmPlan(await request('/api/commerce/plan', { action, params }));
  }
  function confirmPlan(plan) {
    pendingPlan = plan;
    confirmationId = crypto.randomUUID();
    const label = plan.label.startsWith('确认') ? plan.label : `确认${plan.label}`;
    dialog(
      label,
      `${commerceSummary(plan.summary)}<p class="muted">确认后执行本次范围；服务端数据变化时需要重新确认。</p>`,
      actionButton(label, 'confirm', {}, 'primary'),
    );
  }
  async function resultDialog(response) {
    const operation = response.operation?.data;
    const done = operation?.status === 'completed';
    const result = response.result || {};
    const tradeAction = ['trade.orders.create', 'trade.orders.pay'].includes(operation?.action);
    pendingTradePaymentUri = response.checkoutUrl && tradeAction ? result.orderUri || operation?.params?.orderUri || null : null;
    dialog(
      done ? '操作结果已保存' : operation?.status === 'failed' ? '本次操作未成功' : '执行结果待核验',
      `<p>${esc(operation?.message)}</p>${response.checkoutUrl ? `<p>完成支付后关闭支付页返回工作台，系统会自动查询订单状态。</p><a class="button primary" href="${esc(url(response.checkoutUrl))}" target="_blank" rel="noopener">前往支付</a>` : ''}${response.paymentError ? `<p>${esc(response.paymentError)}</p>` : ''}
      ${operation ? relatedOrder({ ...operation, result }) : ''}${operation?.action?.startsWith('memberships.') ? '<p>支付完成与权益到账分别核验，请返回会员页检查订单。</p>' : ''}`,
      done ? actionButton('刷新页面数据', 'refresh') : recoveryActions(response.operation),
    );
    setDirty(false);
    state.loaded = null;
  }
  async function handle(action, target) {
    const id = target.dataset.id;
    if (action === 'commerce-photo-remove') {
      const form = target.closest('form'),
        key = target.dataset.field;
      if (!form || uploading.has(form) || !['imgs', 'deliveryCertificateImgs'].includes(key)) return;
      const value = form.elements.namedItem(key);
      const images = value.value.split('\n').filter(Boolean);
      images.splice(Number(target.dataset.index), 1);
      value.value = images.join('\n');
      form.querySelector(`[data-commerce-photos="${key}"]`).innerHTML = photoList(key, images);
      setDirty(true);
      return;
    }
    if (action === 'commerce-refresh') {
      await load(currentRoute, true);
      return;
    }
    if (action === 'commerce-tab') {
      state.tab = target.dataset.tab;
      state.pageNumber = 1;
      await load(currentRoute, true);
      return;
    }
    if (action === 'commerce-page') {
      state.pageNumber = Number(target.dataset.page);
      await load(currentRoute, true);
      return;
    }
    if (action === 'commerce-goods-filter') {
      state.goodsType = Number(target.dataset.type);
      state.pageNumber = 1;
      await load(currentRoute, true);
      return;
    }
    if (action === 'commerce-orders-filter') {
      state.orderFilter = target.dataset.filter;
      state.pageNumber = 1;
      await load(currentRoute, true);
      return;
    }
    if (action === 'commerce-confirm') {
      if (!pendingPlan) throw new Error('请重新检查操作范围');
      // ID 在确认单生成时创建；网页重试同一确认也沿用原 ID。
      const result = await request('/api/commerce/execute', { planId: pendingPlan.id, planHash: pendingPlan.hash, commandId: confirmationId });
      pendingPlan = null;
      await resultDialog(result);
      return;
    }
    if (action === 'commerce-resume-membership') {
      const history = await request('/api/commerce/history', {});
      const original = history.operations.find((entry) => entry.id === id && entry.data.action === 'memberships.checkout');
      if (!original) throw new Error('原会员请求不存在或账户已变化');
      pendingResumeId = id;
      dialog(
        '继续原会员购买请求',
        `${commerceSummary(original.data.scope)}<p>将沿用原商品版本与请求编号。已创建的订单会继续原单，付款完成后可刷新权益。</p>`,
        actionButton('确认继续原请求', 'confirm-resume-membership', {}, 'primary'),
      );
      return;
    }
    if (action === 'commerce-confirm-resume-membership') {
      if (!pendingResumeId) throw new Error('请重新查看原会员请求');
      const result = await request('/api/commerce/resume-membership', { operationId: pendingResumeId });
      pendingResumeId = null;
      await resultDialog(result);
      return;
    }
    if (action === 'commerce-recover') {
      await resultDialog(await request('/api/commerce/recover', { operationId: id }));
      return;
    }
    if (action === 'commerce-replan') {
      confirmPlan(await request('/api/commerce/replan', { operationId: id }));
      return;
    }
    if (action === 'commerce-favorite') return preview(`trade.favorites.${target.dataset.change}`, { uri: id });
    if (action === 'commerce-membership-buy') return preview('memberships.checkout', { sku: target.dataset.sku });
    if (action === 'commerce-membership-pay') return preview('memberships.purchases.pay', { uri: id });
    if (action === 'commerce-order-cancel') return preview('trade.orders.cancel', { orderUri: id });
    if (action === 'commerce-membership-detail') {
      const detail = await query('memberships.purchases.detail', { uri: id, refresh: 1 });
      dialog(
        '会员订单与权益',
        `${commerceSummary({ product: detail.product })}${pairs([
          ['支付状态', detail.paymentRequired === false ? '无需付款' : payStates[detail.paymentState] || detail.paymentState],
          ['权益状态', fulfillmentStates[detail.fulfillmentState] || detail.fulfillmentState],
          ['订单编号', id],
        ])}<p>${detail.purchaseConfirmed ? (detail.paymentRequired === false ? '试用权益已发放，无需付款。' : '付款已确认，会员权益已发放。') : '付款与权益仍以服务端查询结果为准。'}</p>`,
        detail.paymentState === 'unpaid' ? actionButton('继续支付', 'membership-pay', { id }, 'primary') : actionButton('刷新会员权益', 'refresh'),
      );
      return;
    }
    if (action === 'commerce-buy' || action === 'commerce-order-address') {
      if (action === 'commerce-order-address' && target.dataset.addressId) {
        return preview('trade.orders.address', { orderUri: id, addressId: Number(target.dataset.addressId) });
      }
      const addresses = await query('trade.addresses.list', { page: 1, pageNum: 50 });
      const addingAddress = action === 'commerce-order-address';
      editing = addingAddress ? { action: 'trade.orders.address', orderUri: id } : { action: 'trade.orders.create', uri: id };
      dialog(
        '选择收货地址',
        `<form id="commerce-order-form"><p>${addingAddress ? '为这笔已付款订单选择收货地址，确认同步后通知卖家发货。' : '选择后将查询含运费的最终金额，再由你确认购买。'}</p><label>收货地址<select name="addressId" required>${(addresses.list || []).map((a) => `<option value="${esc(a.id)}">${esc(addressText(a))}</option>`).join('')}</select></label></form>`,
        `${actionButton('新增地址', 'address-edit')}${addresses.list?.length ? actionButton(addingAddress ? '核对订单与地址' : '核对商品与金额', 'order-preview', {}, 'primary') : ''}`,
      );
      return;
    }
    if (action === 'commerce-order-preview') {
      const { action: operation, ...scope } = editing;
      return preview(operation, {
        ...scope,
        addressId: Number(formValues(document.querySelector('#commerce-order-form')).addressId),
        ...(operation === 'trade.orders.create' ? { payMethod: 23 } : {}),
      });
    }
    if (action === 'commerce-order-pay') return preview('trade.orders.pay', { orderUri: id, payMethod: 23 });
    if (action === 'commerce-order-receive') return preview('trade.orders.receive', { orderUri: id });
    if (['commerce-address-default', 'commerce-address-delete'].includes(action))
      return preview(`trade.addresses.${action.endsWith('default') ? 'default' : 'delete'}`, { id });
    if (action === 'commerce-address-edit') {
      const [address, countries] = await Promise.all([
        id ? query('trade.addresses.detail', { id }).then((result) => result.detail) : {},
        query('trade.addresses.countries', { scene: 'address' }),
      ]);
      editing = { action: id ? 'trade.addresses.update' : 'trade.addresses.add', ...(id ? { id } : {}) };
      dialog(
        id ? '编辑收货地址' : '新增收货地址',
        `<form id="commerce-edit-form" class="commerce-form">${['firstName', 'lastName', 'streetAddress', 'additionalAddressInfo', 'city', 'addressState', 'postalCode', 'phoneCountryCode', 'phoneNumber'].map((key) => input(key, address[key] || '', ['firstName', 'lastName', 'streetAddress'].includes(key))).join('')}<label>国家／地区<select name="countryCode" required>${(countries.list || []).map((country) => `<option value="${esc(country.code)}" ${country.code === (address.countryCode || countries.default?.code) ? 'selected' : ''}>${esc(country.name)}</option>`).join('')}</select></label></form>`,
        actionButton('检查地址', 'form-preview', {}, 'primary'),
      );
      return;
    }
    if (action === 'commerce-goods-state') return preview(`trade.seller.goods.${target.dataset.change}`, { uri: id });
    if (action === 'commerce-goods-edit') {
      const goods = id ? await query('trade.seller.goods.detail', { uri: id }) : {};
      if (!id) {
        const eligibility = await query('trade.seller.eligibility');
        if (eligibility.waitDeliveryOrderUri) {
          dialog(
            '请先处理待发货订单',
            `<p>完成当前订单的发货后，再发布新商品。</p>${link('查看待发货订单', 'selling', null, eligibility.waitDeliveryOrderUri, 'button primary')}`,
          );
          return;
        }
      }
      // 发布一级类型与市场搜索分类是两份不同的合同。
      const categories = {
        list: [
          { id: 10, name: '硬币' },
          { id: 20, name: '纸币' },
        ],
      };
      editing = { action: id ? 'trade.seller.goods.update' : 'trade.seller.goods.create', ...(id ? { uri: id } : {}) };
      dialog(
        id ? '编辑商品' : '发布商品',
        `<form id="commerce-edit-form" class="commerce-form">${input('title', goods.title)}<label>分类<select name="category" required>${(categories.list || []).map((category) => `<option value="${esc(category.id)}" ${category.id === goods.category ? 'selected' : ''}>${esc(category.name)}</option>`).join('')}</select></label>${input('salePrice', goods.salePrice, true, 'number')}${input('postage', goods.postage, true, 'number')}${textarea('description', goods.description)}${photoField('imgs', goods.imageList || [], '商品照片')}<label>国际配送<select name="isGlobalShipping"><option value="0">仅境内</option><option value="1" ${goods.isGlobalShipping ? 'selected' : ''}>支持国际配送</option></select></label>${input('globalPostage', goods.globalPostage, false, 'number')}</form>`,
        actionButton('检查发布内容', 'form-preview', {}, 'primary'),
      );
      return;
    }
    if (action === 'commerce-order-deliver') {
      editing = { action: 'trade.orders.deliver', orderUri: id };
      dialog(
        '填写发货信息',
        `<form id="commerce-edit-form" class="commerce-form"><input type="hidden" name="type" value="1">${input('logisticsCompany')}${input('logisticsTrackingNumber')}${input('email', '', false, 'email')}${photoField('deliveryCertificateImgs', [], '发货凭证照片')}</form>`,
        actionButton('检查发货信息', 'form-preview', {}, 'primary'),
      );
      return;
    }
    if (action === 'commerce-feedback') {
      editing = { action: 'trade.orders.feedback-add', orderUri: id };
      dialog(
        '反馈订单问题',
        `<form id="commerce-edit-form" class="commerce-form">${textarea('content')}${photoField('imgs', [], '补充照片（选填）')}</form>`,
        actionButton('检查反馈内容', 'form-preview', {}, 'primary'),
      );
      return;
    }
    if (action === 'commerce-logistics' || action === 'commerce-feedback-detail') {
      const data = await query(action === 'commerce-logistics' ? 'trade.orders.logistics' : 'trade.orders.feedback', { orderUri: id });
      const entries = data.list || data.trackList || [];
      dialog(
        action === 'commerce-logistics' ? '物流进度' : '订单反馈',
        `${pairs([
          ['物流公司', data.logisticsCompany],
          ['物流单号', data.logisticsTrackingNumber],
          ['说明', data.content || data.description],
        ])}${entries.map((entry) => `<article><h3>${esc(entry.title || entry.statusText || '')}</h3><p>${esc(entry.content || entry.description || entry.desc || '')}</p><small>${esc(entry.formatTime || entry.date || entry.time || '')}</small><div class="commerce-thumbnails">${(entry.imgs || []).map((src) => picture(src, '反馈照片')).join('')}</div></article>`).join('') || '<p>服务暂未返回更多进度。</p>'}`,
      );
      return;
    }
    if (action === 'commerce-paypal-edit' || action === 'commerce-withdraw') {
      const data = await query('trade.seller.withdrawal-info');
      editing = { action: action === 'commerce-withdraw' ? 'trade.seller.withdraw' : 'trade.seller.paypal' };
      dialog(
        action === 'commerce-withdraw' ? '申请提现' : '设置收款账户',
        `<form id="commerce-edit-form" class="commerce-form">${input('paypalName', data.paypalName)}${input('paypalEmail', data.paypalEmail, true, 'email')}${action === 'commerce-withdraw' ? input('money', '', true, 'number') : ''}</form>`,
        actionButton('检查提交内容', 'form-preview', {}, 'primary'),
      );
      return;
    }
    if (action === 'commerce-form-preview') {
      const form = document.querySelector('#commerce-edit-form');
      if (uploading.has(form)) throw new Error('照片仍在上传，请完成后再检查提交内容');
      if (!form.reportValidity()) return;
      const params = { ...editing, ...formValues(form) },
        operation = params.action;
      delete params.action;
      // 发货邮箱选填；CLI 的文本合同区分“未提供”与非法空字符串。
      // 只省略此选填字段，必填邮箱（如收款账户）仍由表单和 CLI 正常校验。
      if (operation === 'trade.orders.deliver' && !params.email?.trim()) delete params.email;
      for (const key of ['salePrice', 'postage', 'globalPostage', 'money', 'category', 'isGlobalShipping', 'type']) {
        if (key in params) {
          if (params[key] === '') delete params[key];
          else params[key] = Number(params[key]);
        }
      }
      for (const key of ['imgs', 'deliveryCertificateImgs']) {
        if (key in params) {
          params[key] = params[key]
            .split('\n')
            .map((line) => line.trim())
            .filter(Boolean);
          if (!params[key].length) delete params[key];
        }
      }
      if (
        (operation.startsWith('trade.seller.goods.') && !params.imgs?.length) ||
        (operation === 'trade.orders.deliver' && !params.deliveryCertificateImgs?.length)
      ) {
        throw new Error('请先选择并上传至少一张照片');
      }
      await preview(operation, params);
    }
  }
  async function upload(files, picker) {
    const form = picker.closest('form'),
      key = picker.dataset.commerceUpload,
      originalEditor = editing;
    if (!form || !originalEditor || !['imgs', 'deliveryCertificateImgs'].includes(key) || !files.length) return;
    if (uploading.has(form)) throw new Error('请等待当前照片上传完成');
    const value = form.elements.namedItem(key),
      images = value.value.split('\n').filter(Boolean);
    if (images.length + files.length > 9) throw new Error('每份材料最多 9 张照片，请先移除多余照片');
    for (const file of files) {
      if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type) || file.size <= 0 || file.size > 20 * 1024 * 1024) {
        throw new Error(`${file.name}：请选择不超过 20 MiB 的 JPG、PNG 或 WebP 图片`);
      }
    }
    const status = form.querySelector(`[data-commerce-upload-status="${key}"]`);
    uploading.add(form);
    picker.disabled = true;
    setDirty(true);
    const errors = [];
    try {
      for (const [index, file] of files.entries()) {
        // 对话框或编辑对象已经切换时，停止后续上传，迟到的响应也不能串入新表单。
        if (!form.isConnected || editing !== originalEditor) break;
        status.textContent = `正在上传 ${index + 1} / ${files.length}：${file.name}`;
        try {
          const media = await request(`/api/commerce/upload?${new URLSearchParams({ name: file.name })}`, file, { binary: true });
          if (!form.isConnected || editing !== originalEditor) break;
          // 选图即授权上传文件；商品发布、发货或售后提交仍由后续确认单单独确认。
          const plan = await request('/api/commerce/plan', { action: 'file.upload', params: { mediaId: media.id } });
          if (!form.isConnected || editing !== originalEditor) break;
          const response = await request('/api/commerce/execute', { planId: plan.id, planHash: plan.hash, commandId: crypto.randomUUID() });
          if (response.operation?.data.status !== 'completed' || !url(response.result?.fileUrl))
            throw new Error(response.operation?.data.message || '上传结果待核验，请查看执行记录');
          if (!form.isConnected || editing !== originalEditor) break;
          images.push(response.result.fileUrl);
          value.value = images.join('\n');
          form.querySelector(`[data-commerce-photos="${key}"]`).innerHTML = photoList(key, images);
        } catch (error) {
          errors.push(`${file.name}：${error.message}`);
        }
      }
    } finally {
      uploading.delete(form);
      picker.disabled = false;
      picker.value = '';
      if (form.isConnected && editing === originalEditor)
        status.textContent = `已选 ${images.length} 张照片${errors.length ? `，${errors.length} 张上传未完成` : ''}。`;
    }
    if (errors.length) throw new Error(errors.join('；'));
  }
  async function submit(form) {
    if (form.dataset.commerceForm === 'search') {
      state.keyword = formValues(form).keyword.trim();
      state.pageNumber = 1;
      await load(currentRoute, true);
    }
    if (form.id === 'commerce-edit-form') await handle('commerce-form-preview', { dataset: {} });
    if (form.id === 'commerce-order-form') await handle('commerce-order-preview', { dataset: {} });
  }
  async function checkPaymentReturn() {
    const orderUri = pendingTradePaymentUri;
    if (!orderUri || !commercePages.has(currentRoute.page) || document.visibilityState !== 'visible') return;
    // focus 和 visibilitychange 可能连续触发，短时间内合并为一次查单。
    const now = Date.now();
    if (now - lastPaymentReturnCheck < 1500) return;
    lastPaymentReturnCheck = now;
    try {
      const detail = await query('trade.orders.detail', { orderUri });
      const state = detail.stateDetail || {};
      dialog(
        '已重新查询订单状态',
        `${pairs([
          ['订单编号', orderUri],
          ['当前状态', orderStates[state.state] || state.orderStatus || '待查询'],
        ])}<p>${esc(state.orderDescription || '状态来自服务端订单查询；支付页的浏览器回流不作为付款成功依据。')}</p>${link('查看订单', 'buying', null, orderUri, 'button primary')}`,
      );
      // 付款之后订单进入后续履约状态，无需再为同一支付尝试重复查单。
      if (state.state !== 100) pendingTradePaymentUri = null;
      if (currentRoute.item === orderUri) await load(currentRoute, true);
    } catch (error) {
      toast(`返回工作台后查单失败：${error.message}`);
    }
  }
  const cancelEdit = () => {
    // 关闭交易编辑器代表放弃尚未确认的表单；释放该编辑器持有的脏状态，
    // 否则上传过照片后会永远无法导航。其他业务页面的脏状态不属于这里。
    if (editing) setDirty(false);
    editing = null;
    pendingPlan = null;
    confirmationId = null;
    pendingResumeId = null;
  };
  const deactivate = () => {
    generation += 1;
    state.key = null;
    state.loaded = null;
    state.loading = false;
    cancelEdit();
  };
  return { render, load, handle, submit, upload, deactivate, cancelEdit, checkPaymentReturn };
}
