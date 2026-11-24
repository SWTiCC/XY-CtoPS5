import React from 'react';
import {
  AbsoluteFill,
  Audio,
  Img,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import { BLUE, CYAN, DIM, FPS, GOLD, MONO, PURPLE, SANS, TEXT, VOID, alpha } from './theme';
import { PS5_TOTAL, S, VOICE_OF, type SegmentKey } from './timeline';
import { ScanShot, type ScanTarget } from './ScanShot';

// ============================================================================
// XY-CtoPS5 v0.3 — 科幻版介绍 + 教程片  1920×1080 @ 30fps
// 视觉语言：星云粒子 / 透视网格 / 扫描取景 / HUD 状态行 / 镜头推近
// 标注镜头改用「扫描线 + L 形取景框 + 逐字打字标签」，不再画矩形框
// ============================================================================

// ---------------------------------------------------------------------------
// 背景：星云 + 数据流 + 透视网格 + 扫描线 + 暗角
// ---------------------------------------------------------------------------
const StarField: React.FC = () => {
  const frame = useCurrentFrame();
  // 确定性伪随机粒子（禁止 Math.random，否则每帧漂移且不可复现）
  const stars = React.useMemo(
    () =>
      Array.from({ length: 90 }, (_, i) => {
        const seed = i * 9301 + 49297;
        return {
          x: ((seed * 7) % 1920) / 1920,
          y: ((seed * 13) % 1080) / 1080,
          speed: 0.1 + (i % 5) * 0.06,
          size: 1 + (i % 4) * 0.6,
          alpha: 0.2 + ((i % 7) / 7) * 0.45,
          tone: i % 3,
        };
      }),
    [],
  );
  return (
    <AbsoluteFill>
      {stars.map((star, i) => {
        const y = (star.y * 1080 + frame * star.speed * 0.35) % 1080;
        const x = star.x * 1920 + Math.sin((frame + i * 40) / 70) * 14;
        const color = star.tone === 0 ? CYAN : star.tone === 1 ? BLUE : PURPLE;
        return (
          <div
            key={i}
            style={{
              position: 'absolute',
              left: x % 1920,
              top: y,
              width: star.size,
              height: star.size,
              borderRadius: '50%',
              background: color,
              opacity: star.alpha,
              boxShadow: `0 0 ${star.size * 4}px ${alpha(color, 0.6)}`,
            }}
          />
        );
      })}
    </AbsoluteFill>
  );
};

const Backdrop: React.FC<{ accent?: string }> = ({ accent = CYAN }) => {
  const frame = useCurrentFrame();
  const drift = Math.sin(frame / 110) * 30;
  const scan = (frame * 4) % 1300;
  return (
    <AbsoluteFill style={{ background: VOID, overflow: 'hidden' }}>
      <StarField />
      {/* 星云辉光 */}
      <div
        style={{
          position: 'absolute',
          width: 1500,
          height: 1100,
          left: '48%',
          top: '44%',
          transform: `translate(-50%, -50%) translateY(${drift}px)`,
          background: `radial-gradient(ellipse, ${alpha(accent, 0.13)} 0%, ${alpha(PURPLE, 0.07)} 40%, transparent 70%)`,
          filter: 'blur(50px)',
        }}
      />
      {/* 透视网格地面 */}
      <div
        style={{
          position: 'absolute',
          inset: -300,
          backgroundImage: `linear-gradient(${alpha(BLUE, 0.07)} 1px, transparent 1px), linear-gradient(90deg, ${alpha(BLUE, 0.07)} 1px, transparent 1px)`,
          backgroundSize: '80px 80px',
          transform: `perspective(700px) rotateX(68deg) translateY(${((frame * 0.5) % 80) - 80}px)`,
          transformOrigin: 'center 105%',
          maskImage: 'linear-gradient(to top, black 0%, transparent 68%)',
          WebkitMaskImage: 'linear-gradient(to top, black 0%, transparent 68%)',
        }}
      />
      {/* 扫描线 */}
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          height: 2,
          top: scan,
          background: `linear-gradient(90deg, transparent, ${alpha(accent, 0.55)}, transparent)`,
          opacity: 0.18,
        }}
      />
      {/* 暗角 */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: 'radial-gradient(ellipse at center, transparent 45%, rgba(0,0,0,0.62) 100%)',
        }}
      />
    </AbsoluteFill>
  );
};

/** 旋转能量环：主环 + 反向虚线环 + 刻度弧 */
const Halo: React.FC<{ size?: number; color?: string; opacity?: number; ticks?: boolean }> = ({
  size = 900,
  color = CYAN,
  opacity = 0.15,
  ticks = false,
}) => {
  const frame = useCurrentFrame();
  return (
    <>
      <div
        style={{
          position: 'absolute',
          width: size,
          height: size,
          left: '50%',
          top: '50%',
          transform: `translate(-50%,-50%) rotate(${frame * 0.4}deg)`,
          border: `1px solid ${alpha(color, opacity)}`,
          borderRadius: '50%',
          boxShadow: `0 0 80px ${alpha(color, 0.09)} inset`,
        }}
      />
      <div
        style={{
          position: 'absolute',
          width: size * 0.72,
          height: size * 0.72,
          left: '50%',
          top: '50%',
          transform: `translate(-50%,-50%) rotate(${-frame * 0.6}deg)`,
          border: `1px dashed ${alpha(color, opacity * 0.5)}`,
          borderRadius: '50%',
        }}
      />
      {ticks ? (
        <div
          style={{
            position: 'absolute',
            width: size * 1.12,
            height: size * 1.12,
            left: '50%',
            top: '50%',
            transform: `translate(-50%,-50%) rotate(${frame * 0.15}deg)`,
            borderRadius: '50%',
            background: `repeating-conic-gradient(from 0deg, ${alpha(color, 0.34)} 0deg 0.45deg, transparent 0.45deg 6deg)`,
            maskImage: `radial-gradient(circle, transparent ${size * 0.52}px, black ${size * 0.53}px, black ${size * 0.55}px, transparent ${size * 0.56}px)`,
            WebkitMaskImage: `radial-gradient(circle, transparent ${size * 0.52}px, black ${size * 0.53}px, black ${size * 0.55}px, transparent ${size * 0.56}px)`,
          }}
        />
      ) : null}
    </>
  );
};

const Cap: React.FC<{ text: string; from: number }> = ({ text, from }) => {
  const frame = useCurrentFrame();
  const p = interpolate(frame, [from, from + 14], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return (
    <div
      style={{
        position: 'absolute',
        bottom: 60,
        width: '100%',
        textAlign: 'center',
        opacity: p,
        color: DIM,
        fontSize: 24,
        fontFamily: MONO,
        letterSpacing: 3,
      }}
    >
      {text}
    </div>
  );
};

// ---------------------------------------------------------------------------
// 开场：品牌 + 两种玩法（不讲原理，原理留给下一段）
// ---------------------------------------------------------------------------
const SceneIntro: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const reveal = interpolate(frame, [6, 46], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const spacing = interpolate(frame, [6, 54], [70, 6], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const sub = spring({ frame: frame - 44, fps, config: { damping: 200 }, durationInFrames: 26 });
  const pills = [0, 1].map((i) =>
    spring({ frame: frame - (86 + i * 12), fps, config: { damping: 200 }, durationInFrames: 22 }),
  );

  const pillData = [
    { label: '键鼠映射', sub: 'KEYBOARD + MOUSE', tone: CYAN },
    { label: 'DualSense 直通', sub: 'GYRO · ADAPTIVE TRIGGER', tone: PURPLE },
  ];

  return (
    <AbsoluteFill>
      <Halo size={1180} ticks />
      <Halo size={780} color={PURPLE} opacity={0.1} />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          fontFamily: SANS,
        }}
      >
        <div
          style={{
            fontSize: 148,
            fontWeight: 800,
            letterSpacing: spacing,
            color: TEXT,
            // 用「模糊聚焦 + 字距收拢」揭示：不用 clipPath/overflow，否则 textShadow 会被硬切成矩形亮块
            opacity: reveal,
            filter: `blur(${(1 - reveal) * 14}px)`,
            textShadow: `0 0 ${55 + 20 * Math.sin(frame / 18)}px ${alpha(CYAN, 0.42)}, 0 0 120px ${alpha(BLUE, 0.2)}`,
          }}
        >
          XY-CtoPS5
        </div>
        <div
          style={{
            marginTop: 22,
            fontSize: 40,
            letterSpacing: 10,
            color: CYAN,
            opacity: sub,
            transform: `translateY(${(1 - sub) * 20}px)`,
            textShadow: `0 0 26px ${alpha(CYAN, 0.4)}`,
          }}
        >
          用键盘鼠标玩 PS5
        </div>

        {/* 两种玩法：逐个咬合出现 */}
        <div style={{ marginTop: 62, display: 'flex', gap: 28 }}>
          {pillData.map((p, i) => (
            <div
              key={p.label}
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                padding: '20px 46px',
                borderRadius: 14,
                border: `1.5px solid ${alpha(p.tone, 0.55)}`,
                background: alpha(p.tone, 0.06),
                boxShadow: `0 0 40px ${alpha(p.tone, 0.16)}, inset 0 0 30px ${alpha(p.tone, 0.05)}`,
                opacity: pills[i],
                transform: `translateY(${(1 - pills[i]) * 22}px) scale(${0.94 + pills[i] * 0.06})`,
              }}
            >
              <span style={{ fontSize: 34, color: TEXT, fontWeight: 700, letterSpacing: 2 }}>{p.label}</span>
              <span style={{ marginTop: 8, fontFamily: MONO, fontSize: 14, color: alpha(p.tone, 0.85), letterSpacing: 2 }}>
                {p.sub}
              </span>
            </div>
          ))}
        </div>

        <div
          style={{
            marginTop: 54,
            fontFamily: MONO,
            fontSize: 15,
            color: alpha(DIM, 0.75),
            letterSpacing: 5,
            opacity: pills[1],
          }}
        >
          HDMI CAPTURE · REMOTE PLAY INPUT CHANNEL · GPL-3.0
        </div>
      </div>
      <Audio src={staticFile(VOICE_OF('intro'))} />
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// 原理：两路并行（画面 / 输入）
// ---------------------------------------------------------------------------
const NodeCard: React.FC<{
  x: number;
  y: number;
  label: string;
  sub: string;
  delay: number;
  color: string;
}> = ({ x, y, label, sub, delay, color }) => {
  const frame = useCurrentFrame();
  const p = spring({ frame: frame - delay, fps: FPS, config: { damping: 200 }, durationInFrames: 22 });
  return (
    <div
      style={{
        position: 'absolute',
        left: x,
        top: y,
        width: 300,
        height: 168,
        borderRadius: 14,
        background: 'rgba(8,14,24,0.84)',
        border: `1.5px solid ${alpha(color, 0.6)}`,
        boxShadow: `0 0 40px ${alpha(color, 0.2)}, 0 24px 70px rgba(0,0,0,0.6), inset 0 0 30px ${alpha(color, 0.07)}`,
        opacity: p,
        transform: `perspective(900px) rotateX(${(1 - p) * 22}deg) translateY(${(1 - p) * 40}px)`,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        fontFamily: SANS,
        backdropFilter: 'blur(6px)',
      }}
    >
      <div style={{ fontSize: 34, color: TEXT, fontWeight: 700 }}>{label}</div>
      <div style={{ fontSize: 16, color: DIM, marginTop: 8, fontFamily: MONO, letterSpacing: 1 }}>{sub}</div>
    </div>
  );
};

/** 连线：路径生长 + 沿路径跑动的数据包 */
const FlowLine: React.FC<{
  x1: number;
  x2: number;
  y: number;
  delay: number;
  color: string;
  label: string;
}> = ({ x1, x2, y, delay, color, label }) => {
  const frame = useCurrentFrame();
  const p = interpolate(frame, [delay, delay + 26], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const pulse = 0.45 + 0.55 * Math.sin((frame - delay) / 8);
  const travel = interpolate(frame, [delay + 20, delay + 26], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const dim = `${x1}-${y}`;
  return (
    <svg style={{ position: 'absolute', left: 0, top: 0, width: 1920, height: 1080 }}>
      <defs>
        {/* 必须用 userSpaceOnUse：线段 bbox 高度为 0，用默认的 objectBoundingBox 会让渐变退化、描边整体消失 */}
        <linearGradient id={`fg-${dim}`} x1={x1} y1={y} x2={x2} y2={y} gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor={color} stopOpacity="0.12" />
          <stop offset="55%" stopColor={color} stopOpacity={pulse} />
          <stop offset="100%" stopColor={color} stopOpacity="0.9" />
        </linearGradient>
      </defs>
      <line
        x1={x1}
        y1={y}
        x2={x1 + (x2 - x1) * p}
        y2={y}
        stroke={`url(#fg-${dim})`}
        strokeWidth={2.5}
        strokeDasharray="10 7"
      />
      {/* 数据包：只在连线长成后开始跑 */}
      {travel > 0 ? (
        <circle
          cx={x1 + (x2 - x1) * ((frame * 0.022) % 1)}
          cy={y}
          r={4}
          fill={color}
          opacity={alpha(color, 0.9)}
          style={{ filter: `drop-shadow(0 0 8px ${color})` }}
        />
      ) : null}
      <text
        x={(x1 + x2) / 2}
        y={y - 16}
        fill={color}
        fontSize={17}
        textAnchor="middle"
        fontFamily={MONO}
        letterSpacing={2}
        opacity={p}
      >
        {label}
      </text>
    </svg>
  );
};

const SceneDiagram: React.FC = () => {
  const frame = useCurrentFrame();
  const title = interpolate(frame, [0, 20], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  return (
    <AbsoluteFill>
      <div style={{ position: 'absolute', top: 56, width: '100%', textAlign: 'center', opacity: title }}>
        <div style={{ fontFamily: MONO, fontSize: 15, color: alpha(CYAN, 0.8), letterSpacing: 6 }}>TWO CHANNELS</div>
        <div
          style={{
            marginTop: 10,
            fontSize: 46,
            color: TEXT,
            fontFamily: SANS,
            fontWeight: 800,
            letterSpacing: 6,
            textShadow: `0 0 30px ${alpha(CYAN, 0.27)}`,
          }}
        >
          画面与输入分两路
        </div>
      </div>
      {/* 画面路 */}
      <NodeCard x={110} y={240} label="PS5" sub="游戏主机" delay={8} color={CYAN} />
      <NodeCard x={720} y={240} label="采集卡" sub="HDMI 环出 · 低延迟" delay={16} color={BLUE} />
      <NodeCard x={1330} y={240} label="画面" sub="PC 上显示" delay={24} color={BLUE} />
      <FlowLine x1={430} x2={700} y={324} delay={30} color={BLUE} label="HDMI" />
      <FlowLine x1={1040} x2={1310} y={324} delay={40} color={BLUE} label="CAPTURE" />
      {/* 输入路 */}
      <NodeCard x={110} y={620} label="键鼠 / 手柄" sub="你的操作" delay={56} color={PURPLE} />
      <NodeCard x={720} y={620} label="Remote Play" sub="输入通道" delay={64} color={PURPLE} />
      <NodeCard x={1330} y={620} label="虚拟手柄" sub="伪装成 DualShock" delay={72} color={CYAN} />
      <FlowLine x1={430} x2={700} y={704} delay={78} color={PURPLE} label="INPUT" />
      <FlowLine x1={1040} x2={1310} y={704} delay={88} color={PURPLE} label="PAD" />
      <Cap text="画面：采集卡  /  输入：Remote Play" from={24} />
      <Audio src={staticFile(VOICE_OF('diagram'))} />
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// 教程段：扫描取景镜头
// ---------------------------------------------------------------------------
const ShotModes: React.FC = () => {
  const targets: ScanTarget[] = [
    { x: 0.272, y: 0.143, w: 0.695, h: 0.07, head: 'MODE', detail: '玩法：键鼠 / 手柄', tag: 'below' },
  ];
  return (
    <ScanShot
      image="images/connect-quick-v3.png"
      title="先选玩法"
      subtitle="连接页顶部切换；连接之后要改，需要先断开"
      voice={VOICE_OF('modes')}
      targets={targets}
      index={1}
    />
  );
};

const ShotConnect1: React.FC = () => {
  const targets: ScanTarget[] = [
    { x: 0.273, y: 0.289, w: 0.36, h: 0.07, head: 'HOST', detail: '填 IP 或扫描局域网', tag: 'right' },
    { x: 0.273, y: 0.587, w: 0.5, h: 0.148, head: 'PAIR', detail: 'Account ID + 8 位 PIN', tag: 'right' },
  ];
  return (
    <ScanShot
      image="images/connect-unpaired-v3.png"
      title="第一次配对"
      subtitle="PSN Account ID 与 PS5 上显示的 8 位 PIN"
      voice={VOICE_OF('connect1')}
      targets={targets}
      index={2}
    />
  );
};

const ShotConnect2: React.FC = () => {
  const targets: ScanTarget[] = [
    { x: 0.27, y: 0.324, w: 0.696, h: 0.205, head: 'PAIRED', detail: '已配对在线 → 直接连接', tag: 'below' },
  ];
  return (
    <ScanShot
      image="images/connect-quick-v3.png"
      title="已配对直接连"
      subtitle="凭据已保存；IP 变了也能按主机身份自动找回"
      voice={VOICE_OF('connect2')}
      targets={targets}
      index={3}
    />
  );
};

const ShotMapping1: React.FC = () => {
  const targets: ScanTarget[] = [
    { x: 0.273, y: 0.254, w: 0.667, h: 0.05, head: 'PRESET', detail: '预设 = 一整套按键', tag: 'below' },
    { x: 0.273, y: 0.314, w: 0.667, h: 0.052, head: 'MODE', detail: '模式用切换键循环', tag: 'below' },
  ];
  return (
    <ScanShot
      image="images/mapping-page-v3.png"
      title="预设与模式"
      subtitle="选中即生效；一个预设内部可以有多套模式"
      voice={VOICE_OF('mapping1')}
      targets={targets}
      index={4}
    />
  );
};

const ShotMapping2: React.FC = () => {
  const targets: ScanTarget[] = [
    { x: 0.291, y: 0.498, w: 0.653, h: 0.148, head: 'BIND', detail: '改键 / 编辑 / 删除 · 自动保存', tag: 'right' },
    { x: 0.273, y: 0.722, w: 0.685, h: 0.052, head: 'STICK', detail: '左摇杆方向键单独编辑', tag: 'below' },
  ];
  return (
    <ScanShot
      image="images/mapping-page-v3.png"
      title="按键列表"
      subtitle="支持单按钮、组合键与序列宏"
      voice={VOICE_OF('mapping2')}
      targets={targets}
      index={5}
    />
  );
};

const ShotController: React.FC = () => {
  const targets: ScanTarget[] = [
    { x: 0.277, y: 0.467, w: 0.709, h: 0.257, head: 'GYRO', detail: '陀螺仪 → 右摇杆', tag: 'right' },
    { x: 0.277, y: 0.766, w: 0.47, h: 0.186, head: 'RUMBLE', detail: '震动转发 · 自适应扳机', tag: 'right' },
  ];
  return (
    <ScanShot
      image="images/controller-page.png"
      title="手柄玩法"
      subtitle="USB 或蓝牙接到电脑；PS5 仍在连接页建立会话"
      voice={VOICE_OF('controller')}
      targets={targets}
      index={6}
    />
  );
};

const ShotRun1: React.FC = () => {
  const targets: ScanTarget[] = [
    { x: 0.28, y: 0.254, w: 0.656, h: 0.047, head: 'CAPTURE', detail: '开始捕获 / F8', tag: 'right' },
    { x: 0.266, y: 0.72, w: 0.706, h: 0.051, head: 'WINDOW', detail: '捕获时切到的窗口', tag: 'below' },
  ];
  return (
    <ScanShot
      image="images/run-page-v3.png"
      title="开始捕获"
      subtitle="先选窗口，再开始捕获；键鼠交给 PS5 后指针隐藏"
      voice={VOICE_OF('run1')}
      targets={targets}
      index={7}
    />
  );
};

const ShotRun2: React.FC = () => {
  const targets: ScanTarget[] = [
    { x: 0.263, y: 0.4, w: 0.688, h: 0.196, head: 'AIM', detail: '死区 · 灵敏度 · 平滑 · 反死区', tag: 'below' },
  ];
  return (
    <ScanShot
      image="images/run-page-v3.png"
      title="鼠标手感"
      subtitle="拖动即时生效，松手自动保存"
      voice={VOICE_OF('run2')}
      targets={targets}
      index={8}
    />
  );
};

const ShotRun3: React.FC = () => {
  const targets: ScanTarget[] = [
    { x: 0.263, y: 0.592, w: 0.568, h: 0.098, head: 'TRIGGER', detail: 'R2 / L2 深度 · 滚轮调', tag: 'right' },
  ];
  return (
    <ScanShot
      image="images/run-page-v3.png"
      title="扳机深度"
      subtitle="设定按下时输出多深；捕获中用滚轮加深 / 减浅"
      voice={VOICE_OF('run3')}
      targets={targets}
      index={9}
    />
  );
};

// ---------------------------------------------------------------------------
// GTA6 推荐设置：整图展示
// ---------------------------------------------------------------------------
const FullImageShot: React.FC<{ image: string; title: string; sub: string; voice: string }> = ({
  image,
  title,
  sub,
  voice,
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const enter = spring({ frame, fps: FPS, config: { damping: 200 }, durationInFrames: 24 });
  const zoom = 1 + 0.05 * Math.min(1, frame / durationInFrames);
  const titleP = interpolate(frame, [14, 34], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  return (
    <AbsoluteFill>
      <div style={{ position: 'absolute', top: 40, width: '100%', textAlign: 'center', opacity: titleP }}>
        <div style={{ fontFamily: MONO, fontSize: 14, color: alpha(GOLD, 0.85), letterSpacing: 6 }}>GTA6 · RECOMMENDED</div>
        <div
          style={{
            marginTop: 8,
            fontSize: 40,
            color: TEXT,
            fontFamily: SANS,
            fontWeight: 800,
            letterSpacing: 5,
            textShadow: `0 0 30px ${alpha(GOLD, 0.33)}`,
          }}
        >
          {title}
        </div>
      </div>
      <div
        style={{
          position: 'absolute',
          left: 334,
          top: 132,
          width: 1251,
          height: 870,
          borderRadius: 12,
          overflow: 'hidden',
          border: `1px solid ${alpha(GOLD, 0.3)}`,
          boxShadow: `0 40px 120px rgba(0,0,0,0.75), 0 0 90px ${alpha(GOLD, 0.13)}`,
          opacity: enter,
          transform: `scale(${0.97 + enter * 0.03})`,
        }}
      >
        <Img src={staticFile(image)} style={{ width: '100%', height: '100%', objectFit: 'contain', transform: `scale(${zoom})` }} />
      </div>
      <div
        style={{
          position: 'absolute',
          top: 1026,
          width: '100%',
          textAlign: 'center',
          fontFamily: SANS,
          fontSize: 20,
          color: alpha(DIM, 0.9),
          letterSpacing: 3,
          opacity: titleP,
        }}
      >
        {sub}
      </div>
      <Audio src={staticFile(voice)} />
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// 结尾
// ---------------------------------------------------------------------------
const SceneOutro: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const logo = spring({ frame, fps, config: { damping: 200 }, durationInFrames: 24 });
  const info = interpolate(frame, [28, 52], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  return (
    <AbsoluteFill>
      <Halo size={880} ticks />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          fontFamily: SANS,
        }}
      >
        <div
          style={{
            fontSize: 100,
            fontWeight: 800,
            letterSpacing: 8,
            color: TEXT,
            opacity: logo,
            transform: `scale(${0.9 + logo * 0.1})`,
            textShadow: `0 0 60px ${alpha(CYAN, 0.4)}, 0 0 140px ${alpha(BLUE, 0.2)}`,
          }}
        >
          XY-CtoPS5
        </div>
        <div
          style={{
            marginTop: 30,
            fontSize: 34,
            color: CYAN,
            opacity: info,
            letterSpacing: 4,
            textShadow: `0 0 24px ${alpha(CYAN, 0.33)}`,
          }}
        >
          GitHub 开源 · GPL-3.0
        </div>
        <div style={{ marginTop: 14, fontSize: 23, color: DIM, opacity: info, letterSpacing: 2 }}>
          键鼠 / DualSense 双玩法 · 一个安装程序
        </div>
        <div style={{ marginTop: 40, fontFamily: MONO, fontSize: 15, color: alpha(DIM, 0.6), letterSpacing: 4, opacity: info }}>
          HDMI CAPTURE + REMOTE PLAY · 仅建议单人单机游戏
        </div>
      </div>
      <Audio src={staticFile(VOICE_OF('outro'))} />
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// 时间轴与音轨
// ---------------------------------------------------------------------------
const SCENES: { key: SegmentKey; comp: React.ReactNode }[] = [
  { key: 'intro', comp: <SceneIntro /> },
  { key: 'diagram', comp: <SceneDiagram /> },
  { key: 'modes', comp: <ShotModes /> },
  { key: 'connect1', comp: <ShotConnect1 /> },
  { key: 'connect2', comp: <ShotConnect2 /> },
  { key: 'mapping1', comp: <ShotMapping1 /> },
  { key: 'mapping2', comp: <ShotMapping2 /> },
  { key: 'controller', comp: <ShotController /> },
  { key: 'run1', comp: <ShotRun1 /> },
  { key: 'run2', comp: <ShotRun2 /> },
  { key: 'run3', comp: <ShotRun3 /> },
  {
    key: 'gta6a',
    comp: <FullImageShot image="images/推荐1.png" title="灵敏度" sub="瞄准与视角灵敏度全部 14 · 响应曲线线性" voice={VOICE_OF('gta6a')} />,
  },
  {
    key: 'gta6b',
    comp: (
      <FullImageShot
        image="images/推荐2.png"
        title="战斗"
        sub="自由瞄准 3/3 · 辅助瞄准 0 · 射击辅助关 · 驾驶辅助开"
        voice={VOICE_OF('gta6b')}
      />
    ),
  },
  { key: 'outro', comp: <SceneOutro /> },
];

const Bgm: React.FC = () => <Audio src={staticFile('audio/bgm-tech-house.mp3')} volume={() => 0.15} />;

/** 转场音效：统一在每段起点前 4 帧落 */
const SFX_DEFS: { from: number; src: string; volume: number }[] = [
  { from: 22, src: 'impact-cine.mp3', volume: 0.5 },
  { from: 30, src: 'sparkle.mp3', volume: 0.3 },
  ...([
    ['diagram', 'whoosh-fast.mp3', 0.4],
    ['modes', 'transition-snap.mp3', 0.4],
    ['connect1', 'whoosh-big.mp3', 0.38],
    ['connect2', 'transition-soft.mp3', 0.34],
    ['mapping1', 'whoosh-fast.mp3', 0.38],
    ['mapping2', 'transition-snap.mp3', 0.38],
    ['controller', 'whoosh-big.mp3', 0.38],
    ['run1', 'transition-soft.mp3', 0.34],
    ['run2', 'whoosh-fast.mp3', 0.36],
    ['run3', 'transition-soft.mp3', 0.33],
    ['gta6a', 'whoosh-big.mp3', 0.42],
    ['gta6b', 'whoosh-big.mp3', 0.42],
  ] as [SegmentKey, string, number][]).map(([seg, src, volume]) => ({
    from: Math.max(0, S[seg].from - 4),
    src,
    volume,
  })),
  { from: PS5_TOTAL - 200, src: 'riser-cine.mp3', volume: 0.45 },
  { from: PS5_TOTAL - 130, src: 'impact-cine.mp3', volume: 0.55 },
];

const SfxTrack: React.FC = () => (
  <>
    {SFX_DEFS.map((item, i) => (
      <Sequence key={`${item.src}-${i}`} from={item.from} durationInFrames={90}>
        <Audio src={staticFile(`audio/${item.src}`)} volume={item.volume} />
      </Sequence>
    ))}
  </>
);

export const Ps5Main: React.FC = () => (
  <AbsoluteFill style={{ background: VOID }}>
    {/* 背景只在最外层渲一次：星云/网格/扫描线沿全片时间连续，切镜头时不跳 */}
    <Backdrop />
    <Bgm />
    <SfxTrack />
    {SCENES.map(({ key, comp }) => (
      <Sequence key={key} from={S[key].from} durationInFrames={S[key].duration}>
        {comp}
      </Sequence>
    ))}
  </AbsoluteFill>
);
