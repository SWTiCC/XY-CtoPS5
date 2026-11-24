// XY-CtoPS5 视频视觉 tokens
// 配色从软件 UI 自身生长：深底 #0b0e13、主蓝 #3b82f6、强调青 #38e1ff。
// 科幻片里机器色（扫描线 / 取景框 / 标签 / 状态行）统一用 CYAN，产品界面截图里不出现。

export const VOID = '#03050a';
export const TEXT = '#eef4ff';
export const DIM = '#7f92ad';
export const CYAN = '#38e1ff';
export const BLUE = '#4d8dff';
export const PURPLE = '#a06bff';
export const GOLD = '#ffc46b';

export const SANS = '"Microsoft YaHei", "Noto Sans SC", sans-serif';
export const MONO = '"Cascadia Mono", "Consolas", monospace';

export const FPS = 30;

/** 把 #rrggbb 加上透明度，返回 8 位 hex（Remotion 里比 rgba 好拼接） */
export const alpha = (hex: string, a: number) =>
  `${hex}${Math.round(Math.max(0, Math.min(1, a)) * 255)
    .toString(16)
    .padStart(2, '0')}`;
