// 扫描取景镜头 —— 改编自 Video_Shotcraft 的 scanline-annotate-focus 镜头卡。
//
// 镜头卡原参数（钴蓝机器视线 × 暖沙官网）按比例换算到 1120×933 的窗口，机器色换成产品青。
// 以下参数是卡片里调校过的"命门"，不得随意降档：
//   · 扫描线严格匀速，不加缓动（加了就像有人在拖进度条）
//   · 取景框 spring damping 15 / stiffness 210（一次可见过冲），从外扩 54px 收拢
//   · 臂长晚 3 帧收一档 30→20（跟随感）
//   · 触发帧 = 扫描线越过目标 bbox 下缘那一帧，按下缘排序后钳制最小间隔 8 帧
//
// 与镜头卡的一处关键偏离（终检后改）：
//   卡片把文字标签贴在页面内 bbox 旁边。本项目截的是密集的桌面 UI，实测下来
//   任何 below 落位都会压住下一行内容，密集两行时还会互相重叠、甚至被窗口裁掉。
//   所以窗内只保留「取景框 + 左上角编号徽章」，文字全部移到左栏信息面板，
//   框与文字靠编号 01/02 对应。字仍然逐字打出来，保留"机器在写"的感觉。
import React from 'react';
import { Audio, AbsoluteFill, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from 'remotion';
import { CYAN, DIM, FPS, MONO, SANS, TEXT, alpha } from './theme';

/** 截图窗（帧坐标）。比例 1.2，与截图 1409×1171 基本一致，cover 不裁内容。 */
export const WIN = { x: 520, y: 72, w: 1120, h: 933 };

/** 目标 bbox 用相对截图的比例（0–1）表述，改版式时只动这里。 */
export type ScanTarget = {
  x: number;
  y: number;
  w: number;
  h: number;
  head: string; // 编号旁的主名（等宽大写）
  detail: string; // 左栏说明（逐字打出）
};

const Y0 = -20; // 扫描线起点（窗内 y）
const Y1 = WIN.h + 20;
const SCAN0 = 6;

const clamp01 = (v: number) => Math.max(0, Math.min(1, v));

const ramp = (frame: number, start: number, dur: number) =>
  interpolate(frame, [start, start + dur], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

/** 计算每个目标的触发帧：扫描线越过 bbox 下缘那一帧，按时间排序后钳制最小间隔 */
const scheduleTargets = (targets: ScanTarget[], scanSpan: number) => {
  const frameAtY = (yRel: number) => SCAN0 + ((yRel * WIN.h - Y0) / (Y1 - Y0)) * scanSpan;
  const list = targets.map((t) => ({ t, ft: frameAtY(t.y + t.h) }));
  list.sort((a, b) => a.ft - b.ft);
  let prev = -99;
  for (const item of list) {
    item.ft = Math.max(item.ft, prev + 8);
    prev = item.ft;
  }
  return list;
};

// ───────────────────────── 取景框 ─────────────────────────
const Bracket: React.FC<{ t: ScanTarget; frame: number; fired: number }> = ({ t, frame, fired }) => {
  if (frame < fired) return null;
  const s = spring({ frame: frame - fired, fps: FPS, config: { damping: 15, stiffness: 210 } });
  const pad = 54 * (1 - s); // 外扩 54px → 0（过冲时略收进 bbox）
  const arm = 30 - 10 * ramp(frame, fired + 3, 12); // 臂长晚一拍收一档
  const flash = ramp(frame, fired + 3, 3) * (1 - ramp(frame, fired + 6, 12)); // 对焦闪
  const x = t.x * WIN.w - pad;
  const y = t.y * WIN.h - pad;
  const w = t.w * WIN.w + pad * 2;
  const h = t.h * WIN.h + pad * 2;
  const d = [
    `M${x} ${y + arm}V${y}H${x + arm}`,
    `M${x + w - arm} ${y}H${x + w}V${y + arm}`,
    `M${x + w} ${y + h - arm}V${y + h}H${x + w - arm}`,
    `M${x + arm} ${y + h}H${x}V${y + h - arm}`,
  ].join('');
  return (
    <>
      {/* 对焦瞬间：框内一层极淡青底 + 2px 内描边，一闪即退 */}
      <div
        style={{
          position: 'absolute',
          left: t.x * WIN.w,
          top: t.y * WIN.h,
          width: t.w * WIN.w,
          height: t.h * WIN.h,
          borderRadius: 4,
          background: alpha(CYAN, 0.075 * flash),
          boxShadow: `inset 0 0 0 2px ${alpha(CYAN, 0.4 * flash)}`,
        }}
      />
      <svg
        width={WIN.w}
        height={WIN.h}
        style={{
          position: 'absolute',
          left: 0,
          top: 0,
          overflow: 'visible',
          opacity: Math.min(1, (frame - fired) / 3),
          // 深色截图上 2.6px 青线太弱，用投影补一圈外发光，才读得出"取景框"
          filter: `drop-shadow(0 0 5px ${alpha(CYAN, 0.85)})`,
        }}
      >
        <path d={d} fill="none" stroke={CYAN} strokeWidth={3} strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </>
  );
};

// ───────────────────────── 编号徽章（取代窗内文字标签）─────────────────────────
const BADGE = 27;

const Badge: React.FC<{ t: ScanTarget; frame: number; fired: number; order: number }> = ({
  t,
  frame,
  fired,
  order,
}) => {
  if (frame < fired) return null;
  const pop = ramp(frame, fired + 4, 7);
  // 贴在 bbox 左边缘外侧、沿高度居中：既不会压到框上方的说明行，也不会压到框内内容
  const left = Math.min(WIN.w - BADGE - 6, Math.max(6, t.x * WIN.w - BADGE - 9));
  const centerY = t.y * WIN.h + (t.h * WIN.h) / 2;
  const top = Math.min(WIN.h - BADGE - 6, Math.max(6, centerY - BADGE / 2));
  return (
    <div
      style={{
        position: 'absolute',
        left,
        top,
        width: BADGE,
        height: BADGE,
        borderRadius: 4,
        background: CYAN,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontFamily: MONO,
        fontSize: 14,
        fontWeight: 800,
        color: '#04202b',
        letterSpacing: 0,
        opacity: pop,
        transform: `scale(${0.55 + pop * 0.45})`,
        boxShadow: `0 0 16px ${alpha(CYAN, 0.65)}, 0 2px 8px rgba(0,0,0,0.4)`,
      }}
    >
      {String(order).padStart(2, '0')}
    </div>
  );
};

// ───────────────────────── 左栏信息面板 ─────────────────────────
const HudPanel: React.FC<{
  title: string;
  subtitle: string;
  targets: { t: ScanTarget; ft: number }[];
  frame: number;
  progress: number;
  done: boolean;
  index: number;
}> = ({ title, subtitle, targets, frame, progress, done, index }) => {
  const inP = ramp(frame, 0, 14);
  const firedCount = targets.filter((x) => frame >= x.ft).length;
  return (
    <div
      style={{
        position: 'absolute',
        left: 84,
        top: 92,
        width: 408,
        fontFamily: SANS,
        opacity: inP,
        transform: `translateX(${(1 - inP) * -18}px)`,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
        <span style={{ fontFamily: MONO, fontSize: 17, color: CYAN, letterSpacing: 3, fontWeight: 700 }}>
          SIGNAL {String(index).padStart(2, '0')}
        </span>
        <span style={{ fontFamily: MONO, fontSize: 13, color: alpha(DIM, 0.7), letterSpacing: 2 }}>XY-CTOPS5</span>
      </div>
      <div
        style={{
          marginTop: 14,
          height: 1,
          width: done ? 408 : 408 * clamp01(0.18 + progress * 0.82),
          background: `linear-gradient(90deg, ${CYAN}, ${alpha(CYAN, 0.05)})`,
        }}
      />

      <div style={{ marginTop: 24, fontSize: 40, fontWeight: 800, color: TEXT, letterSpacing: 1.5, lineHeight: 1.16 }}>
        {title}
      </div>
      {/* textWrap: balance 让两行长度均衡，避免出现只有一个字的孤行 */}
      <div
        style={
          {
            marginTop: 10,
            fontSize: 18,
            color: DIM,
            lineHeight: 1.55,
            letterSpacing: 0.4,
            textWrap: 'balance',
          } as React.CSSProperties
        }
      >
        {subtitle}
      </div>

      <div style={{ marginTop: 30 }}>
        {targets.map(({ t, ft }, i) => {
          const lit = frame >= ft;
          const typedLen = Math.min(t.detail.length, Math.max(0, Math.floor((frame - ft - 3) * 1.8)));
          const typing = lit && typedLen < t.detail.length;
          return (
            <div key={t.head} style={{ marginBottom: 20 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span
                  style={{
                    width: 22,
                    height: 22,
                    borderRadius: 3,
                    background: lit ? CYAN : 'transparent',
                    border: `1.5px solid ${lit ? CYAN : alpha(DIM, 0.45)}`,
                    color: lit ? '#04202b' : alpha(DIM, 0.5),
                    fontFamily: MONO,
                    fontSize: 12,
                    fontWeight: 800,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    boxShadow: lit ? `0 0 12px ${alpha(CYAN, 0.5)}` : 'none',
                  }}
                >
                  {String(i + 1).padStart(2, '0')}
                </span>
                <span
                  style={{
                    fontFamily: MONO,
                    fontSize: 16,
                    fontWeight: 700,
                    letterSpacing: 2.5,
                    color: lit ? CYAN : alpha(DIM, 0.45),
                  }}
                >
                  {t.head}
                </span>
              </div>
              <div
                style={{
                  marginLeft: 32,
                  marginTop: 5,
                  minHeight: 24,
                  fontSize: 17,
                  lineHeight: 1.38,
                  color: lit ? TEXT : alpha(DIM, 0.4),
                  letterSpacing: 0.3,
                }}
              >
                {lit ? t.detail.slice(0, typedLen) : t.detail.replace(/[^\s]/g, ' ')}
                {typing ? (
                  <span style={{ display: 'inline-block', width: 2, height: 16, marginLeft: 2, background: CYAN, opacity: 0.8 }} />
                ) : null}
              </div>
            </div>
          );
        })}
      </div>

      {/* 列表与状态行之间补一组竖向刻度：填掉中段空白，也让左栏读起来像一块仪表 */}
      <div style={{ marginTop: 18, height: 150, position: 'relative' }}>
        <div style={{ position: 'absolute', top: 0, left: 0, width: 1, height: 150, background: alpha(CYAN, 0.16) }} />
        {Array.from({ length: 11 }, (_, i) => (
          <div
            key={i}
            style={{
              position: 'absolute',
              top: i * 15,
              left: 0,
              width: i % 5 === 0 ? 26 : 12,
              height: 1,
              background: alpha(CYAN, i % 5 === 0 ? 0.34 : 0.14),
            }}
          />
        ))}
      </div>

      <div style={{ position: 'absolute', top: 520, width: 408 }}>
        <div style={{ display: 'flex', alignItems: 'center', fontFamily: MONO, fontSize: 15, letterSpacing: 2 }}>
          <div
            style={{
              width: 9,
              height: 9,
              borderRadius: 5,
              marginRight: 10,
              background: done ? CYAN : alpha(CYAN, 0.4 + 0.6 * Math.abs(Math.sin(frame / 7))),
              boxShadow: `0 0 0 5px ${alpha(CYAN, 0.1)}`,
            }}
          />
          <span style={{ color: done ? CYAN : TEXT, fontWeight: 700 }}>{done ? 'RESOLVED' : 'SCANNING'}</span>
          <span style={{ marginLeft: 'auto', color: alpha(DIM, 0.8), fontWeight: 600 }}>
            {String(firedCount).padStart(2, '0')} / {String(targets.length).padStart(2, '0')}
          </span>
        </div>
        <div style={{ marginTop: 12, height: 4, width: 408, background: alpha(DIM, 0.16), borderRadius: 2, overflow: 'hidden' }}>
          <div style={{ width: `${(progress * 100).toFixed(2)}%`, height: '100%', background: CYAN, borderRadius: 2 }} />
        </div>
      </div>
    </div>
  );
};

// ───────────────────────── 主镜头 ─────────────────────────
export const ScanShot: React.FC<{
  image: string;
  title: string;
  subtitle: string;
  voice: string;
  targets: ScanTarget[];
  index: number;
  caption?: string;
}> = ({ image, title, subtitle, voice, targets, index, caption }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  // 扫描占本段 55%，限制在 110–300 帧之间（太快读不出"在扫"，太慢像卡住）
  const scanSpan = Math.max(110, Math.min(300, Math.round(durationInFrames * 0.55)));
  const schedule = scheduleTargets(targets, scanSpan);
  const lastFire = Math.max(...schedule.map((x) => x.ft));
  // 进度条走到「最后一个目标被咬合」为止就满；扫描线本身仍按 scanSpan 严格匀速
  const scanProg = clamp01((frame - SCAN0) / Math.max(1, lastFire - SCAN0));
  const lyProg = clamp01((frame - SCAN0) / scanSpan);

  const ly = Y0 + (Y1 - Y0) * lyProg;
  // 机器读完即收线：越过最后一个目标后淡出，不再空扫到底
  const lineOn = ramp(frame, SCAN0 - 4, 5) * (1 - ramp(frame, lastFire + 8, 14));

  // 全程极缓推镜，让画面一直活着
  const push = 1 + 0.05 * ramp(frame, 0, durationInFrames);
  const done = frame >= lastFire + 10;
  const enter = ramp(frame, 0, 16);

  return (
    <AbsoluteFill>
      {/* ── 截图窗 ── */}
      <div
        style={{
          position: 'absolute',
          left: WIN.x,
          top: WIN.y,
          width: WIN.w,
          height: WIN.h,
          borderRadius: 10,
          overflow: 'hidden',
          opacity: enter,
          transform: `scale(${0.985 + enter * 0.015})`,
          boxShadow: `0 34px 90px rgba(0,0,0,0.66), 0 0 0 1px ${alpha(CYAN, 0.2)}, 0 0 70px ${alpha(CYAN, 0.1)}`,
          background: '#0b0e13',
        }}
      >
        <div
          style={{
            position: 'absolute',
            inset: 0,
            transform: `scale(${push})`,
            // 原点压到最上：推镜几乎不动窗口标题栏，多出来的裁切落在底部日志区
            transformOrigin: '50% 2%',
          }}
        >
          <Img src={staticFile(image)} style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />

          {/* 扫描线：3px 光芯 + 身后 140px 渐隐余晖 + 点阵（机器"读过"的痕迹） */}
          {lineOn > 0.01 ? (
            <>
              <div
                style={{
                  position: 'absolute',
                  left: 0,
                  width: WIN.w,
                  top: ly - 140,
                  height: 140,
                  opacity: lineOn,
                  background: `linear-gradient(180deg, ${alpha(CYAN, 0)} 0%, ${alpha(CYAN, 0.05)} 60%, ${alpha(CYAN, 0.14)} 100%)`,
                }}
              />
              <div
                style={{
                  position: 'absolute',
                  left: 0,
                  width: WIN.w,
                  top: ly - 90,
                  height: 90,
                  opacity: lineOn * 0.75,
                  backgroundImage: `radial-gradient(circle, ${alpha(CYAN, 0.5)} 1.2px, transparent 1.8px)`,
                  backgroundSize: '17px 17px',
                  WebkitMaskImage: 'linear-gradient(180deg, transparent, #000)',
                  maskImage: 'linear-gradient(180deg, transparent, #000)',
                }}
              />
              <div
                style={{
                  position: 'absolute',
                  left: 0,
                  width: WIN.w,
                  top: ly - 1.5,
                  height: 3,
                  opacity: lineOn,
                  background: CYAN,
                  boxShadow: `0 0 10px ${alpha(CYAN, 0.6)}, 0 0 26px ${alpha(CYAN, 0.32)}`,
                }}
              />
              {/* 窗内两侧游标随线滑动 */}
              <div
                style={{
                  position: 'absolute',
                  left: 4,
                  top: ly - 7,
                  width: 0,
                  height: 0,
                  opacity: lineOn,
                  borderTop: '7px solid transparent',
                  borderBottom: '7px solid transparent',
                  borderLeft: `10px solid ${CYAN}`,
                }}
              />
              <div
                style={{
                  position: 'absolute',
                  right: 4,
                  top: ly - 7,
                  width: 0,
                  height: 0,
                  opacity: lineOn,
                  borderTop: '7px solid transparent',
                  borderBottom: '7px solid transparent',
                  borderRight: `10px solid ${CYAN}`,
                }}
              />
            </>
          ) : null}

          {/* 取景框 + 编号徽章（同处缩放层，跟随推镜） */}
          {schedule.map(({ t, ft }, i) => (
            <React.Fragment key={t.head}>
              <Bracket t={t} frame={frame} fired={ft} />
              <Badge t={t} frame={frame} fired={ft} order={i + 1} />
            </React.Fragment>
          ))}
        </div>
      </div>

      {/* ── 窗外 HUD：左侧 Y 读数 + 四角短角标 ── */}
      <div
        style={{
          position: 'absolute',
          left: WIN.x - 116,
          top: WIN.y + ly - 10,
          width: 100,
          textAlign: 'right',
          fontFamily: MONO,
          fontSize: 15,
          color: CYAN,
          letterSpacing: 1,
          opacity: lineOn * 0.85,
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        Y {String(Math.max(0, Math.round(ly))).padStart(4, '0')}
      </div>
      {[
        { left: WIN.x - 10, top: WIN.y - 10, bw: 22, bh: 1 },
        { left: WIN.x - 10, top: WIN.y - 10, bw: 1, bh: 22 },
        { left: WIN.x + WIN.w + 10 - 22, top: WIN.y - 10, bw: 22, bh: 1 },
        { left: WIN.x + WIN.w + 10 - 1, top: WIN.y - 10, bw: 1, bh: 22 },
        { left: WIN.x - 10, top: WIN.y + WIN.h + 10 - 1, bw: 22, bh: 1 },
        { left: WIN.x - 10, top: WIN.y + WIN.h + 10 - 22, bw: 1, bh: 22 },
        { left: WIN.x + WIN.w + 10 - 22, top: WIN.y + WIN.h + 10 - 1, bw: 22, bh: 1 },
        { left: WIN.x + WIN.w + 10 - 1, top: WIN.y + WIN.h + 10 - 22, bw: 1, bh: 22 },
      ].map((b, i) => (
        <div
          key={i}
          style={{
            position: 'absolute',
            left: b.left,
            top: b.top,
            width: b.bw,
            height: b.bh,
            background: alpha(CYAN, 0.45),
          }}
        />
      ))}

      <HudPanel
        title={title}
        subtitle={subtitle}
        targets={schedule}
        frame={frame}
        progress={scanProg}
        done={done}
        index={index}
      />

      {/* 右栏：竖排 HUD，平衡左侧信息栏的构图 */}
      <div
        style={{
          position: 'absolute',
          left: 1706,
          top: 168,
          height: 700,
          width: 26,
          borderLeft: `1px solid ${alpha(CYAN, 0.22)}`,
          opacity: enter,
        }}
      />
      {Array.from({ length: 9 }, (_, i) => (
        <div
          key={i}
          style={{
            position: 'absolute',
            left: 1706,
            top: 168 + (660 / 8) * i,
            width: i % 4 === 0 ? 12 : 6,
            height: 1,
            background: alpha(CYAN, i % 4 === 0 ? 0.5 : 0.24),
            opacity: enter,
          }}
        />
      ))}
      <div
        style={{
          position: 'absolute',
          left: 1730,
          top: 300,
          fontFamily: MONO,
          fontSize: 13,
          letterSpacing: 8,
          color: alpha(CYAN, 0.42),
          writingMode: 'vertical-rl',
          whiteSpace: 'nowrap',
          opacity: enter,
        }}
      >
        HDMI CAPTURE / REMOTE PLAY INPUT CHANNEL
      </div>

      {/* 底部基线 */}
      <div
        style={{
          position: 'absolute',
          left: 88,
          top: 1042,
          width: 1744,
          height: 1,
          background: `linear-gradient(90deg, ${alpha(CYAN, 0.35)}, ${alpha(CYAN, 0.06)} 55%, transparent)`,
          opacity: enter,
        }}
      />

      {caption ? (
        <div
          style={{
            position: 'absolute',
            left: WIN.x,
            top: WIN.y + WIN.h + 22,
            width: WIN.w,
            textAlign: 'center',
            fontFamily: MONO,
            fontSize: 17,
            color: alpha(DIM, 0.9),
            letterSpacing: 2,
            opacity: ramp(frame, lastFire + 6, 14),
          }}
        >
          {caption}
        </div>
      ) : null}

      <Audio src={staticFile(voice)} />
    </AbsoluteFill>
  );
};
