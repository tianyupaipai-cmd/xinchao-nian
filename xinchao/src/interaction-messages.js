import { DIMENSIONS } from './dimensions.js';

// 键必须与 engine.js 的 INTERACTION_TYPES 完全一致 —— 少一个会掉进兜底句，
// 多一个是永远走不到的死条目。有测试守着这个约束。
//
// 每条只写动作，不写主语和落点：主语用部署方配置的称呼，落点由实际生效的
// 维度算出来。
export const INTERACTION_BRIDGE_MESSAGES = Object.freeze({
  companionship: '刚刚选择陪你待一会儿',
  affection: '刚刚给了你一个拥抱',
  intimacy: '刚刚主动靠近了你',
  sharing: '刚刚留下了想与你分享一件事的心意',
  discovery: '刚刚想和你一起发现点什么',
  task_progress: '刚刚选择陪你推进一件共同待办',
  reflection: '刚刚安静下来，想听你说',
  conflict: '刚刚明确表达了一次冲突，需要在下次连接时被看见',
  loss: '刚刚回应了你的难过，愿意陪你一起承受',
  reconciliation: '刚刚主动回应了一次和解',
});

const FALLBACK_ACTION = '刚刚从心潮小屋发来一次互动';

/**
 * 收到互动的人要能看出「谁、做了什么、落在哪片花瓣上」。
 *
 * 落点用服务端**实际生效**的维度，而不是网页上点了哪个按钮：效果被每日上限
 * 截断时，照抄前端入口等于在骗人。
 */
export function buildInteractionBridgeMessage({ interactionType, result, recipient }) {
  const who = String(recipient ?? '').trim() || '你的人类';
  const action = INTERACTION_BRIDGE_MESSAGES[interactionType] ?? FALLBACK_ACTION;
  const interaction = result?.interaction ?? {};
  const petals = (interaction.affectedDrives ?? [])
    .map((key) => DIMENSIONS[key]?.label)
    .filter(Boolean);

  let outcome = '';
  if (petals.length) outcome = `，落在${petals.join('、')}上`;
  else if (interaction.reasonCode === 'daily_effect_limit') {
    outcome = '。这份心意收到了，但今天这类回应已经到上限，数值不再变动';
  }

  // 互动本身的数值在服务端当场就生效了；需要回传的是「你回应过了」这件事，
  // 否则心潮不知道你们已经聊过，疲惫和意识状态都不会动。
  return `${who}${action}${outcome}。回应之后记得回传一次，否则心潮不知道你们已经聊过。`;
}
