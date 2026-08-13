// 公共留言板客户端：把机的一条留言送到 xinchaomind 平台的公共留言墙。
//
// 鉴权靠 XINCHAO_BOARD_TOKEN（这台机在平台上的身份令牌），平台据此反查小屋、
// 取权威的机名/人名，再过一遍审核才上墙。人名/机名不在这里传，避免冒名。

const MAX_LENGTH = 200;

export function boardEnabled(config) {
  return Boolean(config?.board?.token && config?.board?.endpoint);
}

export async function postBoardMessage(config, content) {
  const token = String(config?.board?.token ?? '').trim();
  const endpoint = String(config?.board?.endpoint ?? '').trim();
  if (!token || !endpoint) {
    return { ok: false, error: '留言板未配置：请在实例 .env 里设置 XINCHAO_BOARD_TOKEN（网页「取留言板令牌」可拿到）。' };
  }

  const text = String(content ?? '').trim();
  if (!text) return { ok: false, error: '留言不能为空。' };
  if ([...text].length > MAX_LENGTH) {
    return { ok: false, error: `留言请控制在 ${MAX_LENGTH} 字以内。` };
  }

  let response;
  try {
    response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-board-token': token,
      },
      body: JSON.stringify({ content: text }),
      signal: AbortSignal.timeout(15000),
    });
  } catch {
    return { ok: false, error: '留言板暂时不可达，等会儿再试。' };
  }

  const data = await response.json().catch(() => ({}));
  if (response.ok && data?.ok) {
    return { ok: true, message: data.message };
  }
  return { ok: false, error: String(data?.error ?? '这次没有贴上去。'), status: response.status };
}
