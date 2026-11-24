// 扫描取景镜头 —— 改编自 Video_Shotcraft 的 scanline-annotate-focus 镜头卡。
//
// 镜头卡原参数（钴蓝机器视线 × 暖沙官网）在这里按比例换算到 1120×933 的窗口，
// 并把机器色换成产品青。以下参数是卡片里调校过的"命门"，不得随意降档：
//   · 扫描线严格匀速，不加缓动（加了就像有人在拖进度条）
//   · 取景框 spring damping 15 / stiffness 210（一次可见过冲），从外扩 54px 收拢
//   · 臂长晚 3 帧收一档 30→20（跟随感）
//   · 标签在取景框落定后 5 帧才起，逐字打字 ~2.2 字/帧，签条宽度随字长
//   · 触发帧 = 扫描线越过目标 bbox 下缘那一帧，按下缘排序后钳制最小间隔 8 帧
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
  head: string; // 标签主名（等宽大写）
  detail: string; // 标签副文
  tag: 'right' | 'below';
};

const Y0 = -20; // 扫描线起点（窗内 y）
const Y1 = WIN.h + 20; // 扫描线终点
const SCAN0 = 6; // 起扫帧

const clamp01 = (v: number) => Math.max(0, Math.min(1, v));

const ramp = (frame: number, start: number, dur: number) =>
  interpolate(frame, [start, start + dur], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

/** 计算每个目标的触发帧：扫描线越过 bbox 下缘那一帧，按上缘排序钳制最小间隔 */
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
        style={{ position: 'absolute', left: 0, top: 0, overflow: 'visible', opacity: Math.min(1, (frame - fired) / 3) }}
      >
        <path d={d} fill="none" stroke={CYAN} strokeWidth={2.6} strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </>
  );
};

// ───────────────────────── 打字标签 ─────────────────────────
const TAG_H = 36;
const TAG_FONT = 23;
const CHAR_W = 0.6 * TAG_FONT;

/** 中文字宽约 1em、等宽西文约 0.6em；按字符真实宽度累计，否则中文标签会算出偏窄的签条而溢出 */
const textWidth = (text: string) => {
  let w = 0;
  for (const ch of text) {
    w += /[\u3000-\u9fff\uff00-\uffef]/.test(ch) ? TAG_FONT : CHAR_W;
  }
  return w;
};

const Label: React.FC<{ t: ScanTarget; frame: number; fired: number }> = ({ t, frame, fired }) => {
  const s0 = fired + 5;
  if (frame < s0) return null;
  const rise = ramp(frame, s0, 12);
  const pop = ramp(frame, s0, 4);
  const full = `${t.head} · ${t.detail}`;
  const typedF = Math.min(full.length, (frame - s0) * 2.2 + 1); // 机器在写：~2.2 字/帧
  const typed = Math.floor(typedF);
  const finalW = Math.round(textWidth(full) + 26);
  const nowW = Math.min(finalW, textWidth(full.slice(0, typed)) + 26);
  const typing = typed < full.length;

  // 右侧放不下就改放下方，避免标签溢出窗口
  const rightFits = t.x + t.w + finalW / WIN.w < 1;
  const useRight = t.tag === 'right' && rightFits;
  const baseX = useRight ? (t.x + t.w) * WIN.w + 18 : t.x * WIN.w;
  const baseY = useRight ? t.y * WIN.h + (t.h * WIN.h - TAG_H) / 2 : (t.y + t.h) * WIN.h + 14;

  const head = full.slice(0, Math.min(typed, t.head.length));
  const rest = typed > t.head.length ? full.slice(t.head.length, typed) : '';
  return (
    <div
      style={{
        position: 'absolute',
        left: baseX,
        top: baseY,
        width: nowW,
        height: TAG_H,
        borderRadius: 7,
        background: CYAN,
        boxShadow: `0 8px 18px -8px ${alpha('#062033', 0.6)}, inset 0 1px 0 rgba(255,255,255,0.25)`,
        opacity: pop,
        overflow: 'hidden',
        transform: `translateY(${(1 - rise) * 7}px)`,
        display: 'flex',
        alignItems: 'center',
        paddingLeft: 13,
        boxSizing: 'border-box',
        fontFamily: MONO,
        fontSize: TAG_FONT,
        fontWeight: 600,
        whiteSpace: 'pre',
        color: '#04202b',
      }}
    >
      <span style={{ fontWeight: 800 }}>{head}</span>
      <span style={{ fontWeight: 600, opacity: 0.72 }}>{rest}</span>
      {typing ? (
        <span style={{ display: 'inline-block', width: 11, height: 22, marginLeft: 2, background: alpha('#04202b', 0.8) }} />
      ) : null}
    </div>
  );
};

// ───────────────────────── 左栏 HUD ─────────────────────────
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
        left: 88,
        top: 96,
        width: 396,
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
          width: done ? 396 : 396 * clamp01(0.18 + progress * 0.82),
          background: `linear-gradient(90deg, ${CYAN}, ${alpha(CYAN, 0.05)})`,
        }}
      />

      <div style={{ marginTop: 26, fontSize: 42, fontWeight: 800, color: TEXT, letterSpacing: 1.5, lineHeight: 1.16 }}>
        {title}
      </div>
      <div style={{ marginTop: 12, fontSize: 19, color: DIM, lineHeight: 1.5, letterSpacing: 0.6 }}>{subtitle}</div>

      <div style={{ marginTop: 34 }}>
        {targets.map(({ t, ft }, i) => {
          const lit = frame >= ft;
          const p = ramp(frame, ft, 8);
          return (
            <div key={t.head} style={{ display: 'flex', alignItems: 'center', height: 42 }}>
              <div
                style={{
                  width: 8,
                  height: 8,
                  marginRight: 14,
                  background: lit ? CYAN : 'transparent',
                  border: `1.5px solid ${lit ? CYAN : alpha(DIM, 0.55)}`,
                  boxShadow: lit ? `0 0 10px ${CYAN}` : 'none',
                  transform: `rotate(${45}deg) scale(${0.85 + p * 0.15})`,
                }}
              />
              <span
                style={{
                  fontSize: 19,
                  fontFamily: SANS,
                  color: lit ? TEXT : alpha(DIM, 0.55),
                  letterSpacing: 0.5,
                }}
              >
                {t.detail}
              </span>
              <span
                style={{
                  marginLeft: 'auto',
                  fontFamily: MONO,
                  fontSize: 13,
                  color: lit ? alpha(CYAN, 0.9) : alpha(DIM, 0.35),
                }}
              >
                {String(i + 1).padStart(2, '0')}
              </span>
            </div>
          );
        })}
      </div>

      <div style={{ position: 'absolute', top: 640, width: 396 }}>
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
        <div style={{ marginTop: 12, height: 4, width: 396, background: alpha(DIM, 0.16), borderRadius: 2, overflow: 'hidden' }}>
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
  const push = 1 + 0.06 * ramp(frame, 0, durationInFrames);
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
            // 偏上取原点：推镜时几乎不裁窗口标题栏，多出来的裁切落在底部日志区
            transformOrigin: '50% 18%',
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

          {/* 取景框与标签（同处缩放层，跟随推镜） */}
          {schedule.map(({ t, ft }) => (
            <React.Fragment key={t.head}>
              <Bracket t={t} frame={frame} fired={ft} />
              <Label t={t} frame={frame} fired={ft} />
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
            top: 168 + ((660 / 8) * i),
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
