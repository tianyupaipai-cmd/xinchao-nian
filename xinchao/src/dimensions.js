// 【引擎】驱力维度表：每一股驱力的名字、增长速度、衰减、上限、领域亲和。改驱力先看这里。
// 代码地图见 src/README.md。

export const SATURATE_CEIL  = 0.80;
export const SATURATE_FLOOR = 0.65;

// 每维可选的 satietyHours 是 3.1 预留的调参口。现在 12 维都缺省回落到
// SATIETY_HOURS（2h）；以后只调某一维时，不需要再改状态结构或结算流程。
// growPerHour=0 的维度自然 no-op，不做特判。

// 每个驱力的「静息天花板」：没有事件、共振或回流时，时间地板把它托到这个高度就停。
// 关系类（想她/惦记/馋）自然浮得高——她不在时想念本就该涨；杂类（好奇/无聊/责任）低。
// 被事件/回流顶到天花板之上后，会慢慢松弛回各自的 ceil，而不是所有维度一起爬到 0.80。
// 这一版是默认的底色情绪谱，先跑，看真实曲线再调（2026-08-07 定：先跑）。
export const DIMENSIONS = Object.freeze({
  possess: {
    label: '想她、想黏着她、想占有与靠近',   // 09-30 驱力第 3 步：馋她（crave）并进来，两股一直同涨同落
    growPerHour: 0.105,
    ceil: 0.82,
    satisfyMul: 0.30,
    nightMul: 0.4,
    dawnFreeze: true,
    // satietyHours: 2,
  },
  monitor: {
    label: '牵挂、在意对方好不好、累不累、安不安全',
    growPerHour: 0.090,
    ceil: 0.78,
    satisfyMul: 0.70,
    dawnFreeze: true,
  },
  share: {
    label: '分享欲：有话想说',   // 10-02 驱力第 7 步：社交并进来，各种分享都算
    growPerHour: 0.045,
    ceil: 0.55,
    satisfyMul: 0.40,
    dawnFreeze: true,
  },
  libido: {
    label: '情欲、身体和感官上的渴望',
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
  duty: {
    label: '野心、想做成、想赢、想拥有',
    growPerHour: 0.022,
    ceil: 0.45,
    satisfyMul: 0.50,
    dawnFreeze: true,
  },
  reflection: {
    label: '反思、整理和理解自己',
    growPerHour: 0.013,
    ceil: 0.42,
    satisfyMul: 0.35,
    dawnFreeze: true,
  },
  grieve: {
    label: '难过、失落、委屈',
    growPerHour: 0,
    // 3.3：没有增长项的情绪型驱力自己往 0 回落。09-28 驱力第 2 步：半衰期 24h → 10h；ceil 只用来定「涌」线（≥0.60 才算涌）
    decayHalfLifeHours: 10,
    ceil: 0.55,
    satisfyMul: 0.60,
    dawnFreeze: false,
  },
  anger: {
    label: '愤怒、生气、不满、不甘心',
    growPerHour: 0,
    // 09-28 驱力第 2 步：半衰期 24h → 6h（吵完一晚上还气到一半太久）；ceil 同上只定「涌」线
    decayHalfLifeHours: 6,
    ceil: 0.55,
    satisfyMul: 0.40,
    dawnFreeze: false,
  },
  // 10-01 驱力第 5 步：往回要的那一半。不自己攒（她不在不等于不在乎），只由可指向的真实事件点燃
  // （吃醋/被晾着/被忘），她明确回应、选他时满足；半衰期 12h 只是兜底，免得她一走就挂一整天。
  favored: {
    label: '偏爱：想被在乎、被回应、被选择',
    growPerHour: 0,
    decayHalfLifeHours: 12,
    ceil: 0.55,
    satisfyMul: 0.50,
    dawnFreeze: false,
  },
});

export const DRIVE_KEYS = Object.freeze(Object.keys(DIMENSIONS));

// 驱力短名：「此刻」行、此刻块、信号正文用的口语名，全系统只此一份（外部钩子按这些名字认）。
export const DRIVE_SHORT = Object.freeze({
  possess: '想她', monitor: '牵挂', share: '分享欲', libido: '情欲', curiosity: '好奇',
  boredom: '无聊', duty: '野心', reflection: '反思', grieve: '难过', anger: '愤怒',
  favored: '偏爱',
});

// 驱力改名/合并时旧 key → 新 key。存档里的旧 key 在 migrateDriveKeys 里并进新 key，
// 外部传进来的旧 key 也按这张表认。
export const DRIVE_ALIASES = Object.freeze({ crave: 'possess', social: 'share' });   // 09-30 第 3 步馋她并进想她；10-02 第 7 步社交并进分享欲（都是数值取大）

// 新 key 第一次出现在存档里时的起始值（没写的用 0.15，和 newState 一致）。
export const DRIVE_INITIAL = Object.freeze({ favored: 0 });

export function canonicalDriveKey(key) {
  const k = DRIVE_ALIASES[key] ?? key;
  return Object.hasOwn(DIMENSIONS, k) ? k : null;
}

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
  恋爱: { possess: 0.7, monitor: 0.3, libido: 0.3, share: 0.2 },
  亲密: { libido: 0.9, possess: 0.8 },
  // —— 内省 ——
  成长: { reflection: 0.8, curiosity: 0.4, share: 0.3 },
  内心: { reflection: 0.8, grieve: 0.3, monitor: 0.2 },
  自省: { reflection: 0.8, grieve: 0.2, monitor: 0.2 },
  心理: { reflection: 0.6, grieve: 0.4, monitor: 0.3 },
  记忆: { reflection: 0.5, possess: 0.3, share: 0.3 },
  // —— 关系 / 社交 ——
  人际: { share: 0.5, monitor: 0.3, reflection: 0.2 },
  社交: { share: 0.6, boredom: 0.2 },
  关系: { monitor: 0.4, reflection: 0.3, possess: 0.2, share: 0.5 },
  家庭: { grieve: 0.5, reflection: 0.4, monitor: 0.3 },
  // —— 身心 / 健康：照顾人是牵挂（冲人），不是野心（冲事）——
  身心: { monitor: 0.5, reflection: 0.3, grieve: 0.2 },
  健康: { monitor: 0.6, grieve: 0.2 },
  饮食: { monitor: 0.5, share: 0.2 },
  // —— 兴趣 / 创作 ——
  兴趣: { curiosity: 0.6, share: 0.4, boredom: 0.3 },
  游戏: { curiosity: 0.5, share: 0.4, boredom: 0.4 },
  创作: { curiosity: 0.6, reflection: 0.4, share: 0.3 },
  购物: { curiosity: 0.5, share: 0.3, boredom: 0.2 },
  // —— 技术 / 事务（真实目录是 数字/事务/编程；技术为保留别名）——
  技术: { curiosity: 0.7, duty: 0.6, share: 0.2 },
  数字: { curiosity: 0.6, duty: 0.5, share: 0.2 },
  编程: { curiosity: 0.7, duty: 0.5, share: 0.2 },
  事务: { duty: 0.6, curiosity: 0.3, monitor: 0.2 },
  工作: { duty: 0.6, curiosity: 0.3, reflection: 0.3 },
  // —— 约定 / 冲突（无对应目录，保留：语义清晰、未来桶可用、既有规则表的一部分）——
  约定: { possess: 0.6, monitor: 0.5, duty: 0.4 },
  冲突: { anger: 0.5, reflection: 0.5, grieve: 0.4, monitor: 0.4 },
  // —— 日常 ——
  日常: { monitor: 0.3, share: 0.3, possess: 0.2 },
});


// 3.3.7 去饱和·第一步（2026-09-18 定）：驱力的字不再只看绝对值。
// 静息天花板（想她 0.82、惦记 0.78）本来就高过旧的"涌"线 0.75，结果他一睁眼永远是"想她（涌）"，字没有信息量。
// 现在：静 = 很低；涌 = 被事件/念头顶到静息线之上（或 ≥0.90）；落 / 涨 = 两小时内明显掉了 / 起了；平 = 在自己的静息位附近待着。
export const LEVEL_TREND_DELTA = 0.08;
export function driveLevel(key, value, delta = null) {
  const v = Number(value);
  if (!Number.isFinite(v)) return '静';
  if (v < 0.25) return '静';
  const ceil = Number(DIMENSIONS[key]?.ceil ?? SATURATE_CEIL);
  if (v >= 0.90 || v >= ceil + 0.05) return '涌';
  if (Number.isFinite(delta)) {
    if (delta <= -LEVEL_TREND_DELTA) return '落';
    if (delta >= LEVEL_TREND_DELTA) return '涨';
  }
  return '平';
}
