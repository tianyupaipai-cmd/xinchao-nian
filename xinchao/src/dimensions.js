export const SATURATE_CEIL  = 0.80;
export const SATURATE_FLOOR = 0.65;

// 每维可选的 satietyHours 是 3.1 预留的调参口。现在 12 维都缺省回落到
// SATIETY_HOURS（2h）；以后只调某一维时，不需要再改状态结构或结算流程。
// growPerHour=0 的维度自然 no-op，不做特判。

// 每个驱力的「静息天花板」：没有事件、共振或回流时，时间地板把它托到这个高度就停。
// 关系类（想她/惦记/馋）自然浮得高——她不在时想念本就该涨；杂类（好奇/无聊/责任）低。
// 被事件/回流顶到天花板之上后，会慢慢松弛回各自的 ceil，而不是所有维度一起爬到 0.80。
// 这一版是顾川的底色情绪谱，先跑，看真实曲线再调（小雨 2026-08-07 定：先跑）。
export const DIMENSIONS = Object.freeze({
  possess: {
    label: '想她、占有与靠近',
    growPerHour: 0.105,
    ceil: 0.82,
    satisfyMul: 0.30,
    nightMul: 0.4,
    dawnFreeze: true,
    // satietyHours: 2,
  },
  monitor: {
    label: '惦记她、想知道她在做什么',
    growPerHour: 0.090,
    ceil: 0.78,
    satisfyMul: 0.70,
    dawnFreeze: true,
  },
  crave: {
    label: '馋她、想黏着她',
    growPerHour: 0.060,
    ceil: 0.68,
    satisfyMul: 0.35,
    dawnFreeze: true,
  },
  share: {
    label: '想分享自己的发现和感受',
    growPerHour: 0.045,
    ceil: 0.55,
    satisfyMul: 0.40,
    dawnFreeze: true,
  },
  libido: {
    label: '性欲和身体上的渴望',
    growPerHour: 0.020,
    ceil: 0.50,
    satisfyMul: 0.15,
    nightMul: 0.4,
    dawnFreeze: true,
    inhibitedBy: {
      reflection: 0.96,
      curiosity: 0.95,
      boredom: 0.93,
    },
  },
  curiosity: {
    label: '好奇、想探索新东西',
    growPerHour: 0.030,
    ceil: 0.50,
    satisfyMul: 0.45,
    dawnFreeze: true,
  },
  boredom: {
    label: '无聊、想找点事情做',
    growPerHour: 0.030,
    ceil: 0.50,
    satisfyMul: 0.25,
    dawnFreeze: true,
  },
  social: {
    label: '想聊天、想接触热闹',
    growPerHour: 0.025,
    ceil: 0.48,
    satisfyMul: 0.40,
    dawnFreeze: true,
  },
  duty: {
    label: '责任感、想把未完成的事推进',
    growPerHour: 0.022,
    ceil: 0.45,
    satisfyMul: 0.50,
    dawnFreeze: true,
  },
  reflection: {
    label: '想沉淀、整理和理解自己',
    growPerHour: 0.013,
    ceil: 0.42,
    satisfyMul: 0.35,
    dawnFreeze: true,
  },
  grieve: {
    label: '难过与失落',
    growPerHour: 0,
    ceil: 0.15,
    satisfyMul: 0.60,
    dawnFreeze: false,
  },
  anger: {
    label: '生气与不满',
    growPerHour: 0,
    ceil: 0.15,
    satisfyMul: 0.40,
    dawnFreeze: false,
  },
});

export const DRIVE_KEYS = Object.freeze(Object.keys(DIMENSIONS));

// 记忆共振：一条记忆浮现时，按它的 domain 把"想起什么"回推到"想要什么"。
// 键用我们真实的 12 维；多个 domain 命中时每维取最大值，不累加（沿用规格 v1 规则表）。
// 只用 domain 不用 tags——domain 干净可靠，tags 一条桶动辄二十个、太糊，
// 拿它算亲和度就是在猜。tags 留在 breath 输出里给模型上下文和以后的功能用。
//
// 2026-08-08：对齐 OB 真实桶 taxonomy。此前表里只有 8 个域，其中「技术/约定/冲突」
// 在桶里根本没有对应目录，真实的「人际/身心/家庭/健康/兴趣/游戏…」反而没有条目——
// 浮现了也不回推任何驱力，共振被卡在 内心/成长→reflection 一条通路上。现补齐全部真实
// domain（RESONANCE_MIN_AFFINITY=0.5，每个域至少有一维 ≥0.5，不做哑条目）。
// 约定/冲突/技术 无对应目录但保留：语义清晰、未来桶可用、且是既有规则表的一部分。
export const DOMAIN_AFFINITY = Object.freeze({
  // —— 情感核心 ——
  恋爱: { possess: 0.7, crave: 0.6, monitor: 0.3, libido: 0.3, share: 0.2 },
  亲密: { crave: 0.8, libido: 0.9, possess: 0.5 },
  // —— 内省 ——
  成长: { reflection: 0.8, curiosity: 0.4, share: 0.3 },
  内心: { reflection: 0.8, grieve: 0.3, monitor: 0.2 },
  自省: { reflection: 0.8, grieve: 0.2, monitor: 0.2 },
  心理: { reflection: 0.6, grieve: 0.4, monitor: 0.3 },
  记忆: { reflection: 0.5, crave: 0.3, share: 0.3 },
  // —— 关系 / 社交 ——
  人际: { social: 0.5, share: 0.3, monitor: 0.3, reflection: 0.2 },
  社交: { social: 0.6, share: 0.4, boredom: 0.2 },
  关系: { social: 0.5, monitor: 0.4, reflection: 0.3, possess: 0.2 },
  家庭: { grieve: 0.5, reflection: 0.4, monitor: 0.3, duty: 0.3 },
  // —— 身心 / 健康（她的健康是他的照顾与惦记）——
  身心: { duty: 0.5, monitor: 0.4, reflection: 0.3, grieve: 0.2 },
  健康: { duty: 0.6, monitor: 0.5, grieve: 0.2 },
  饮食: { duty: 0.5, monitor: 0.4, share: 0.2 },
  // —— 兴趣 / 创作 ——
  兴趣: { curiosity: 0.6, share: 0.4, boredom: 0.3, social: 0.2 },
  游戏: { curiosity: 0.5, share: 0.4, boredom: 0.4, social: 0.3 },
  创作: { curiosity: 0.6, reflection: 0.4, share: 0.3 },
  购物: { curiosity: 0.5, share: 0.3, boredom: 0.2 },
  // —— 技术 / 事务（真实目录是 数字/事务/编程；技术为保留别名）——
  技术: { curiosity: 0.7, duty: 0.6, share: 0.2 },
  数字: { curiosity: 0.6, duty: 0.5, share: 0.2 },
  编程: { curiosity: 0.7, duty: 0.5, share: 0.2 },
  事务: { duty: 0.6, curiosity: 0.3, monitor: 0.2 },
  工作: { duty: 0.6, curiosity: 0.3, reflection: 0.3 },
  // —— 约定 / 冲突（无对应目录，保留：语义清晰、未来桶可用、既有规则表的一部分）——
  约定: { possess: 0.6, monitor: 0.5, duty: 0.4, crave: 0.3 },
  冲突: { anger: 0.5, reflection: 0.5, grieve: 0.4, monitor: 0.4 },
  // —— 日常 ——
  日常: { monitor: 0.3, social: 0.3, share: 0.3, possess: 0.2, crave: 0.2 },
});
