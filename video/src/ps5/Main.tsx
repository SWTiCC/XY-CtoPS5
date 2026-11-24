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

// ============================================================================
// XY-CtoPS5 v0.3 — 科幻版介绍 + 教程片
// 1920x1080 @ 30fps
// 视觉语言：星云粒子 / 数据流 / 扫描线 / 镜头推近 / 聚光灯 / 发光标签
// 不再使用矩形框标注，改用「镜头聚焦 + 暗角 + 发光文字引导」
// ============================================================================

const VOID = '#03050a';
const TEXT = '#eef4ff';
const DIM = '#7f92ad';
const CYAN = '#38e1ff';
const BLUE = '#4d8dff';
const PURPLE = '#a06bff';
const GOLD = '#ffc46b';

const FPS = 30;

// 时间轴按旁白长度分配（edge-tts 约 48kbps）
const S = {
  intro: { from: 0, duration: 510 },
  diagram: { from: 510, duration: 255 },
  modes: { from: 765, duration: 410 },
  connect1: { from: 1175, duration: 380 },
  connect2: { from: 1555, duration: 525 },
  mapping1: { from: 2080, duration: 375 },
  mapping2: { from: 2455, duration: 510 },
  controller: { from: 2965, duration: 355 },
  run1: { from: 3320, duration: 435 },
  run2: { from: 3755, duration: 365 },
  run3: { from: 4120, duration: 290 },
  gta6a: { from: 4410, duration: 170 },
  gta6b: { from: 4580, duration: 170 },
  outro: { from: 4750, duration: 180 },
} as const;

export const PS5_TOTAL = 4930;

// ---------------------------------------------------------------------------
// 科幻背景：星云 + 数据流 + 透视网格 + 扫描线 + 暗角
// ---------------------------------------------------------------------------
const StarField: React.FC = () => {
  const frame = useCurrentFrame();
  // 确定性伪随机粒子（避免每帧抖动）
  const stars = Array.from({ length: 70 }, (_, i) => {
    const seed = i * 9301 + 49297;
    const x = ((seed * 7) % 1920) + ((frame * (0.15 + (i % 5) * 0.08)) % 1920);
    const y = ((seed * 13) % 1080) + Math.sin((frame + i * 40) / 60) * 24;
    const size = 1 + (i % 4) * 0.6;
    const alpha = 0.25 + ((i % 7) / 7) * 0.5;
    return { x: x % 1920, y, size, alpha };
  });
  return (
    <AbsoluteFill>
      {stars.map((star, i) => (
        <div
          key={i}
          style={{
            position: 'absolute',
            left: star.x,
            top: star.y,
            width: star.size,
            height: star.size,
            borderRadius: '50%',
            background: i % 3 === 0 ? CYAN : i % 3 === 1 ? BLUE : PURPLE,
            opacity: star.alpha,
            boxShadow: `0 0 ${star.size * 4}px ${i % 3 === 0 ? CYAN : BLUE}`,
          }}
        />
      ))}
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
          background: `radial-gradient(ellipse, ${accent}22 0%, ${PURPLE}12 40%, transparent 70%)`,
          filter: 'blur(50px)',
        }}
      />
      {/* 透视网格地面 */}
      <div
        style={{
          position: 'absolute',
          inset: -300,
          backgroundImage:
            'linear-gradient(rgba(90,180,255,0.07) 1px, transparent 1px), linear-gradient(90deg, rgba(90,180,255,0.07) 1px, transparent 1px)',
          backgroundSize: '80px 80px',
          transform: `perspective(700px) rotateX(68deg) translateY(${(frame * 0.5) % 80 - 80}px)`,
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
          background: `linear-gradient(90deg, transparent, ${accent}88, transparent)`,
          opacity: 0.45,
        }}
      />
      {/* 暗角 */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background:
            'radial-gradient(ellipse at center, transparent 45%, rgba(0,0,0,0.62) 100%)',
        }}
      />
    </AbsoluteFill>
  );
};

// 旋转能量环
const Halo: React.FC<{ size?: number; color?: string; opacity?: number }> = ({
  size = 900,
  color = CYAN,
  opacity = 0.15,
}) => {
  const frame = useCurrentFrame();
  const hex = Math.round(opacity * 255).toString(16).padStart(2, '0');
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
          border: `1px solid ${color}${hex}`,
          borderRadius: '50%',
          boxShadow: `0 0 80px ${color}18 inset`,
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
          border: `1px dashed ${color}${Math.round(opacity * 120).toString(16).padStart(2, '0')}`,
          borderRadius: '50%',
        }}
      />
    </>
  );
};

const Cap = ({ text, from }: { text: string; from: number }) => {
  const frame = useCurrentFrame();
  const p = interpolate(frame, [from, from + 14], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return (
    <div
      style={{
        position: 'absolute',
        bottom: 68,
        width: '100%',
        textAlign: 'center',
        opacity: p,
        color: DIM,
        fontSize: 26,
        letterSpacing: 4,
        fontFamily: 'Microsoft YaHei, sans-serif',
      }}
    >
      {text}
    </div>
  );
};

// ---------------------------------------------------------------------------
// 开场
// ---------------------------------------------------------------------------
const SceneIntro: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const reveal = interpolate(frame, [8, 52], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const spacing = interpolate(frame, [8, 60], [72, 6], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const glow = interpolate(frame, [36, 96], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const sub = spring({ frame: frame - 54, fps, config: { damping: 200 }, durationInFrames: 26 });
  const glint = interpolate(frame, [60, 130], [-320, 2400], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill>
      <Backdrop />
      <Halo size={1200} />
      <Halo size={800} color={PURPLE} opacity={0.1} />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          fontFamily: 'Microsoft YaHei, sans-serif',
        }}
      >
        <div
          style={{
            position: 'relative',
            fontSize: 152,
            fontWeight: 800,
            letterSpacing: spacing,
            color: TEXT,
            clipPath: `inset(0 ${(1 - reveal) * 100}% 0 0)`,
            overflow: 'hidden',
            textShadow: `0 0 ${60 * glow}px ${CYAN}77, 0 0 120px ${BLUE}33`,
          }}
        >
          XY-CtoPS5
          <div
            style={{
              position: 'absolute',
              top: 0,
              bottom: 0,
              width: 150,
              left: glint,
              background:
                'linear-gradient(90deg, transparent, rgba(140,230,255,0.55), transparent)',
              transform: 'skewX(-18deg)',
            }}
          />
        </div>
        <div
          style={{
            marginTop: 28,
            fontSize: 46,
            letterSpacing: 12,
            color: CYAN,
            opacity: sub,
            transform: `translateY(${(1 - sub) * 22}px)`,
            textShadow: `0 0 26px ${CYAN}66`,
          }}
        >
          键鼠 · 手柄 · 双玩法
        </div>
        <div
          style={{
            marginTop: 16,
            fontSize: 23,
            letterSpacing: 5,
            color: DIM,
            opacity: sub * 0.9,
          }}
        >
          采集卡画面 · Remote Play 输入通道
        </div>
      </div>
      <Audio src={staticFile('voice/01_intro.mp3')} />
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// 原理：3D 节点 + 光流
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
        height: 170,
        borderRadius: 16,
        background: 'rgba(8,14,24,0.82)',
        border: `1.5px solid ${color}99`,
        boxShadow: `0 0 40px ${color}33, 0 24px 70px rgba(0,0,0,0.6), inset 0 0 30px ${color}12`,
        opacity: p,
        transform: `perspective(900px) rotateX(${(1 - p) * 22}deg) translateY(${(1 - p) * 40}px)`,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        fontFamily: 'Microsoft YaHei, sans-serif',
        backdropFilter: 'blur(6px)',
      }}
    >
      <div style={{ fontSize: 36, color: TEXT, fontWeight: 700 }}>{label}</div>
      <div style={{ fontSize: 17, color: DIM, marginTop: 8 }}>{sub}</div>
    </div>
  );
};

const FlowLine: React.FC<{
  x1: number;
  x2: number;
  y: number;
  delay: number;
  color: string;
  label: string;
}> = ({ x1, x2, y, delay, color, label }) => {
  const frame = useCurrentFrame();
  const p = interpolate(frame, [delay, delay + 26], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const pulse = 0.4 + 0.6 * Math.sin((frame - delay) / 8);
  return (
    <svg style={{ position: 'absolute', left: 0, top: 0, width: 1920, height: 1080 }}>
      <defs>
        <linearGradient id={`fg-${x1}-${y}`} x1="0" x2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.08" />
          <stop offset="55%" stopColor={color} stopOpacity={pulse} />
          <stop offset="100%" stopColor={color} stopOpacity="0.85" />
        </linearGradient>
      </defs>
      <line
        x1={x1}
        y1={y}
        x2={x1 + (x2 - x1) * p}
        y2={y}
        stroke={`url(#fg-${x1}-${y})`}
        strokeWidth={2.5}
        strokeDasharray="10 7"
      />
      <text
        x={(x1 + x2) / 2}
        y={y - 16}
        fill={color}
        fontSize={19}
        textAnchor="middle"
        fontFamily="Microsoft YaHei, sans-serif"
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
      <Backdrop />
      <div style={{ position: 'absolute', top: 66, width: '100%', textAlign: 'center', opacity: title }}>
        <span style={{ fontSize: 48, color: TEXT, fontFamily: 'Microsoft YaHei, sans-serif', fontWeight: 700, letterSpacing: 6, textShadow: `0 0 30px ${CYAN}44` }}>
          两路并行
        </span>
      </div>
      <NodeCard x={110} y={190} label="PS5" sub="游戏主机" delay={8} color={CYAN} />
      <NodeCard x={720} y={190} label="采集卡" sub="HDMI 环出 · 零延迟" delay={16} color={BLUE} />
      <NodeCard x={1330} y={190} label="画面" sub="PC 上显示" delay={24} color={BLUE} />
      <FlowLine x1={430} x2={700} y={280} delay={30} color={BLUE} label="HDMI" />
      <FlowLine x1={1040} x2={1310} y={280} delay={40} color={BLUE} label="采集" />
      <NodeCard x={720} y={530} label="Remote Play" sub="输入通道" delay={64} color={PURPLE} />
      <NodeCard x={1330} y={530} label="键鼠 / 手柄" sub="伪装成手柄" delay={72} color={PURPLE} />
      <FlowLine x1={1040} x2={1310} y={620} delay={82} color={PURPLE} label="手柄协议" />
      <Cap text="画面：采集卡 / 输入：Remote Play" from={24} />
      <Audio src={staticFile('voice/02_diagram.mp3')} />
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// 聚焦截图（镜头推近 + 暗角 + 发光标签，无矩形框）
// 阶段：0-36f 全景淡入 → 36-96f 推近 → 之后停留漂移
// ---------------------------------------------------------------------------
type Focus = { x: number; y: number; w: number; h: number; label: string; delay: number };

const FocusShot: React.FC<{
  image: string;
  title: string;
  voice: string;
  focus: Focus;
  zoomTo?: number;
  caption?: string;
}> = ({ image, title, voice, focus, zoomTo = 1.75, caption }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = spring({ frame, fps, config: { damping: 200 }, durationInFrames: 26 });
  // 推近曲线：0-40f 全景，40-110f 推近，之后微漂
  const zoom = interpolate(frame, [40, 110], [1.0, zoomTo], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const drift = interpolate(frame, [110, 400], [0, 0.02], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const cx = focus.x + focus.w / 2;
  const cy = focus.y + focus.h / 2;
  const titleP = interpolate(frame, [26, 46], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const labelP = interpolate(frame, [100, 124], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const spotlight = interpolate(frame, [40, 110], [0, 0.55], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill>
      <Backdrop />
      <div style={{ position: 'absolute', top: 40, width: '100%', textAlign: 'center', opacity: titleP }}>
        <span
          style={{
            fontSize: 42,
            color: TEXT,
            fontFamily: 'Microsoft YaHei, sans-serif',
            fontWeight: 700,
            letterSpacing: 5,
            textShadow: `0 0 32px ${CYAN}55`,
          }}
        >
          {title}
        </span>
      </div>

      {/* 截图容器：推近 + 聚光 */}
      <div
        style={{
          position: 'absolute',
          left: 210,
          top: 130,
          width: 1500,
          height: 800,
          overflow: 'hidden',
          borderRadius: 10,
          border: '1px solid rgba(90,180,255,0.22)',
          boxShadow: `0 40px 120px rgba(0,0,0,0.75), 0 0 80px ${CYAN}1a`,
          opacity: enter,
          transform: `translateY(${(1 - enter) * 46}px)`,
        }}
      >
        <div
          style={{
            width: '100%',
            height: '100%',
            transformOrigin: `${cx * 100}% ${cy * 100}%`,
            transform: `scale(${zoom + drift})`,
          }}
        >
          <Img src={staticFile(image)} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
        </div>
        {/* 聚光暗角：突出聚焦区域 */}
        <div
          style={{
            position: 'absolute',
            inset: 0,
            opacity: spotlight,
            background: `radial-gradient(circle at ${cx * 100}% ${cy * 100}%, transparent 14%, rgba(3,5,10,0.82) 62%)`,
            pointerEvents: 'none',
          }}
        />
        {/* 聚光描边光晕（不画矩形，只有柔光边） */}
        <div
          style={{
            position: 'absolute',
            left: `${focus.x * 100}%`,
            top: `${focus.y * 100}%`,
            width: `${focus.w * 100}%`,
            height: `${focus.h * 100}%`,
            opacity: spotlight,
            boxShadow: `0 0 40px ${CYAN}88, inset 0 0 40px ${CYAN}33`,
            borderRadius: 12,
            pointerEvents: 'none',
          }}
        />
      </div>

      {/* 发光引导标签（无框） */}
      <div
        style={{
          position: 'absolute',
          left: 210 + focus.x * 1500,
          top: 130 + (focus.y + focus.h) * 800 + 18,
          opacity: labelP,
          transform: `translateY(${(1 - labelP) * 14}px)`,
          display: 'flex',
          alignItems: 'center',
          fontFamily: 'Microsoft YaHei, sans-serif',
        }}
      >
        <div
          style={{
            width: 3,
            height: 22,
            background: CYAN,
            boxShadow: `0 0 12px ${CYAN}`,
            marginRight: 12,
          }}
        />
        <div
          style={{
            fontSize: 22,
            color: CYAN,
            letterSpacing: 1,
            textShadow: `0 0 18px ${CYAN}aa`,
          }}
        >
          {focus.label}
        </div>
      </div>

      {caption ? <Cap text={caption} from={130} /> : null}
      <Audio src={staticFile(voice)} />
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// 全屏图（GTA6 设置）：5 秒停留 + 缓慢推近
// ---------------------------------------------------------------------------
const FullImageShot: React.FC<{ image: string; title: string; voice: string }> = ({
  image,
  title,
  voice,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = spring({ frame, fps, config: { damping: 200 }, durationInFrames: 24 });
  const zoom = interpolate(frame, [0, 170], [1.0, 1.06], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const titleP = interpolate(frame, [16, 36], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  return (
    <AbsoluteFill>
      <Backdrop />
      <div style={{ position: 'absolute', top: 34, width: '100%', textAlign: 'center', opacity: titleP }}>
        <span style={{ fontSize: 40, color: TEXT, fontFamily: 'Microsoft YaHei, sans-serif', fontWeight: 700, letterSpacing: 5, textShadow: `0 0 30px ${GOLD}55` }}>
          {title}
        </span>
      </div>
      <div
        style={{
          position: 'absolute',
          left: 190,
          top: 120,
          width: 1540,
          height: 850,
          borderRadius: 12,
          overflow: 'hidden',
          border: `1px solid ${GOLD}44`,
          boxShadow: `0 40px 120px rgba(0,0,0,0.75), 0 0 90px ${GOLD}22`,
          opacity: enter,
          transform: `scale(${0.97 + enter * 0.03})`,
        }}
      >
        <Img
          src={staticFile(image)}
          style={{ width: '100%', height: '100%', objectFit: 'contain', transform: `scale(${zoom})`, background: '#0a0614' }}
        />
      </div>
      <Audio src={staticFile(voice)} />
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// 文字要点（映射说明等）
// ---------------------------------------------------------------------------
const Bullet: React.FC<{ index: number; title: string; desc: string; color?: string }> = ({
  index,
  title,
  desc,
  color = CYAN,
}) => {
  const frame = useCurrentFrame();
  const p = spring({ frame: frame - index * 30 - 8, fps: FPS, config: { damping: 200 }, durationInFrames: 18 });
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        marginBottom: 30,
        opacity: p,
        transform: `translateX(${(1 - p) * -36}px)`,
      }}
    >
      <div
        style={{
          width: 9,
          height: 9,
          marginTop: 15,
          marginRight: 20,
          background: color,
          borderRadius: 4,
          boxShadow: `0 0 14px ${color}`,
          flexShrink: 0,
        }}
      />
      <div>
        <div style={{ fontSize: 36, color: TEXT, fontWeight: 700, fontFamily: 'Microsoft YaHei, sans-serif' }}>
          {title}
        </div>
        <div style={{ fontSize: 21, color: DIM, marginTop: 6, fontFamily: 'Microsoft YaHei, sans-serif' }}>
          {desc}
        </div>
      </div>
    </div>
  );
};

const SceneModes: React.FC = () => {
  // 玩法选择：用连接页截图，镜头推近顶部「玩法」切换区
  return (
    <FocusShot
      image="images/connect-quick-v3.png"
      title="连接 · 先选玩法"
      voice="voice/03_modes.mp3"
      focus={{ x: 0.27, y: 0.15, w: 0.68, h: 0.06, label: '玩法：键鼠 / 手柄（连接后需断开才能改）', delay: 40 }}
      zoomTo={2.1}
    />
  );
};

const SceneConnect1: React.FC = () => (
  <FocusShot
    image="images/connect-unpaired-v3.png"
    title="连接 · 第一次配对"
    voice="voice/06_connect.mp3"
    focus={{ x: 0.27, y: 0.28, w: 0.70, h: 0.36, label: '填 PS5 IP / 扫描局域网', delay: 40 }}
    zoomTo={1.7}
  />
);

const SceneConnect2: React.FC = () => (
  <FocusShot
    image="images/connect-quick-v3.png"
    title="连接 · 已配对直接连"
    voice="voice/07_connect2.mp3"
    focus={{ x: 0.27, y: 0.16, w: 0.70, h: 0.28, label: '已配对主机在线 → 点直接连接', delay: 40 }}
    zoomTo={1.8}
  />
);

const SceneMapping1: React.FC = () => (
  <FocusShot
    image="images/mapping-page-v3.png"
    title="映射 · 预设与模式"
    voice="voice/08_mapping.mp3"
    focus={{ x: 0.27, y: 0.14, w: 0.70, h: 0.24, label: '预设 = 一整套按键 · 模式用切换键循环', delay: 40 }}
    zoomTo={1.8}
  />
);

const SceneMapping2: React.FC = () => (
  <FocusShot
    image="images/mapping-page-v3.png"
    title="映射 · 按键列表"
    voice="voice/09_mapping2.mp3"
    focus={{ x: 0.27, y: 0.40, w: 0.70, h: 0.30, label: '改键 / 编辑 / 删除 · 左摇杆方向键单独编辑', delay: 40 }}
    zoomTo={1.9}
  />
);

const SceneController: React.FC = () => (
  <FocusShot
    image="images/controller-page.png"
    title="手柄 · 陀螺仪与扳机"
    voice="voice/08_controller.mp3"
    focus={{ x: 0.27, y: 0.44, w: 0.66, h: 0.30, label: '陀螺仪瞄准 · 震动转发 · 自适应扳机', delay: 40 }}
    zoomTo={1.85}
  />
);

const SceneRun1: React.FC = () => (
  <FocusShot
    image="images/run-page-v3.png"
    title="运行 · 开始捕获"
    voice="voice/10_run.mp3"
    focus={{ x: 0.28, y: 0.70, w: 0.68, h: 0.09, label: '① 先选捕获窗口', delay: 40 }}
    zoomTo={1.75}
    caption="② 再点开始捕获 / F8"
  />
);

const SceneRun2: React.FC = () => (
  <FocusShot
    image="images/run-page-v3.png"
    title="运行 · 鼠标手感"
    voice="voice/11_run2.mp3"
    focus={{ x: 0.28, y: 0.36, w: 0.68, h: 0.18, label: '过渡 / 死区 / 灵敏度 / 慢灵敏 / 快灵敏 / 平滑', delay: 40 }}
    zoomTo={1.8}
  />
);

const SceneRun3: React.FC = () => (
  <FocusShot
    image="images/run-page-v3.png"
    title="运行 · 扳机深度"
    voice="voice/12_run3.mp3"
    focus={{ x: 0.28, y: 0.58, w: 0.68, h: 0.14, label: 'R2 / L2 深度 · 滚轮加深减浅', delay: 40 }}
    zoomTo={1.85}
  />
);

const SceneGta6a: React.FC = () => (
  <FullImageShot
    image="images/推荐1.png"
    title="GTA6 推荐设置 · 灵敏度"
    voice="voice/12_gta6_1.mp3"
  />
);

const SceneGta6b: React.FC = () => (
  <FullImageShot
    image="images/推荐2.png"
    title="GTA6 推荐设置 · 战斗"
    voice="voice/13_gta6_2.mp3"
  />
);

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
      <Backdrop />
      <Halo size={900} />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          fontFamily: 'Microsoft YaHei, sans-serif',
        }}
      >
        <div
          style={{
            fontSize: 104,
            fontWeight: 800,
            letterSpacing: 8,
            color: TEXT,
            opacity: logo,
            transform: `scale(${0.9 + logo * 0.1})`,
            textShadow: `0 0 60px ${CYAN}66, 0 0 140px ${BLUE}33`,
          }}
        >
          XY-CtoPS5
        </div>
        <div style={{ marginTop: 32, fontSize: 38, color: CYAN, opacity: info, letterSpacing: 4, textShadow: `0 0 24px ${CYAN}55` }}>
          GitHub 开源 · GPL-3.0
        </div>
        <div style={{ marginTop: 16, fontSize: 25, color: DIM, opacity: info, letterSpacing: 2 }}>
          键鼠 / DualSense 双玩法 · 一个安装程序
        </div>
        <div style={{ marginTop: 44, fontSize: 19, color: DIM, opacity: info * 0.6 }}>
          采集卡 + Remote Play 输入通道 · 仅建议单人单机游戏
        </div>
      </div>
      <Audio src={staticFile('voice/05_outro.mp3')} />
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// 时间轴与音频
// ---------------------------------------------------------------------------
const Shot: React.FC<{ from: number; duration: number; children: React.ReactNode }> = ({
  from,
  duration,
  children,
}) => (
  <Sequence from={from} durationInFrames={duration}>
    {children}
  </Sequence>
);

const SHOTS: { key: keyof typeof S; comp: React.ReactNode }[] = [
  { key: 'intro', comp: <SceneIntro /> },
  { key: 'diagram', comp: <SceneDiagram /> },
  { key: 'modes', comp: <SceneModes /> },
  { key: 'connect1', comp: <SceneConnect1 /> },
  { key: 'connect2', comp: <SceneConnect2 /> },
  { key: 'mapping1', comp: <SceneMapping1 /> },
  { key: 'mapping2', comp: <SceneMapping2 /> },
  { key: 'controller', comp: <SceneController /> },
  { key: 'run1', comp: <SceneRun1 /> },
  { key: 'run2', comp: <SceneRun2 /> },
  { key: 'run3', comp: <SceneRun3 /> },
  { key: 'gta6a', comp: <SceneGta6a /> },
  { key: 'gta6b', comp: <SceneGta6b /> },
  { key: 'outro', comp: <SceneOutro /> },
];

const Bgm: React.FC = () => (
  <Audio
    src={staticFile('audio/bgm-tech-house.mp3')}
    volume={() => 0.15}
  />
);

const SFX_DEFS = [
  { from: 26, src: 'impact-cine.mp3', volume: 0.5 },
  { from: 34, src: 'sparkle.mp3', volume: 0.32 },
  { from: 502, src: 'whoosh-fast.mp3', volume: 0.42 },
  { from: 757, src: 'transition-snap.mp3', volume: 0.42 },
  { from: 1167, src: 'whoosh-big.mp3', volume: 0.4 },
  { from: 1547, src: 'transition-soft.mp3', volume: 0.35 },
  { from: 2072, src: 'whoosh-fast.mp3', volume: 0.42 },
  { from: 2447, src: 'transition-snap.mp3', volume: 0.4 },
  { from: 2957, src: 'whoosh-big.mp3', volume: 0.4 },
  { from: 3312, src: 'transition-soft.mp3', volume: 0.35 },
  { from: 3747, src: 'whoosh-fast.mp3', volume: 0.4 },
  { from: 4112, src: 'transition-soft.mp3', volume: 0.35 },
  { from: 4402, src: 'whoosh-big.mp3', volume: 0.45 },
  { from: 4572, src: 'whoosh-big.mp3', volume: 0.45 },
  { from: 4730, src: 'riser-cine.mp3', volume: 0.5 },
  { from: 4800, src: 'impact-cine.mp3', volume: 0.55 },
];

const SfxTrack: React.FC = () => (
  <>
    {SFX_DEFS.map((item, index) => (
      <Sequence key={`${item.src}-${index}`} from={item.from} durationInFrames={90}>
        <Audio src={staticFile(`audio/${item.src}`)} volume={item.volume} />
      </Sequence>
    ))}
  </>
);

export const Ps5Main: React.FC = () => (
  <AbsoluteFill style={{ background: VOID }}>
    <Bgm />
    <SfxTrack />
    {SHOTS.map(({ key, comp }) => {
      const shot = S[key];
      return (
        <Shot key={key} from={shot.from} duration={shot.duration}>
          {comp}
        </Shot>
      );
    })}
  </AbsoluteFill>
);
