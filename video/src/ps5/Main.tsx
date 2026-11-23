import React from 'react';
import {
  AbsoluteFill,
  Audio,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';

// ============================================================================
// XY-CtoPS5 介绍片 — 纯动效 + 中文旁白
// 45s @ 30fps = 1350f
// 暗色科技风：背景 #0b0f14，强调 #4da3ff，文字 #dbe4ee
// ============================================================================

const BG = '#0b0f14';
const PANEL = '#121a24';
const TEXT = '#dbe4ee';
const DIM = '#7c8b9f';
const ACCENT = '#4da3ff';
const ACCENT2 = '#7ee787';

const FPS = 30;

export const PS5_SHOTS = {
  intro: { from: 0, duration: 180 },
  diagram: { from: 180, duration: 300 },
  mouse: { from: 480, duration: 300 },
  features: { from: 780, duration: 270 },
  outro: { from: 1050, duration: 300 },
} as const;

export const PS5_TOTAL = 1350;

// ---------------------------------------------------------------------------
// 通用：淡入 + 上浮
// ---------------------------------------------------------------------------
const fadeUp = (frame: number, start: number, duration = 18) => {
  const p = interpolate(frame, [start, start + duration], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return { opacity: p, transform: `translateY(${(1 - p) * 24}px)` };
};

const Cap = ({ text, from, style }: { text: string; from: number; style?: React.CSSProperties }) => {
  const frame = useCurrentFrame();
  const p = interpolate(frame, [from, from + 14], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return (
    <div
      style={{
        position: 'absolute',
        bottom: 84,
        width: '100%',
        textAlign: 'center',
        opacity: p,
        color: DIM,
        fontSize: 30,
        letterSpacing: 2,
        fontFamily: 'Microsoft YaHei, sans-serif',
        ...style,
      }}
    >
      {text}
    </div>
  );
};

const Grid = () => (
  <div
    style={{
      position: 'absolute',
      inset: 0,
      backgroundImage:
        'linear-gradient(rgba(77,163,255,0.06) 1px, transparent 1px), linear-gradient(90deg, rgba(77,163,255,0.06) 1px, transparent 1px)',
      backgroundSize: '64px 64px',
    }}
  />
);

// ---------------------------------------------------------------------------
// 场景 1：品牌开场
// ---------------------------------------------------------------------------
const SceneIntro: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const logo = spring({ frame, fps, config: { damping: 200 }, durationInFrames: 26 });
  const sub = fadeUp(frame, 22, 20);
  const glint = interpolate(frame, [30, 90], [-200, 2200], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill style={{ background: BG }}>
      <Grid />
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
            fontSize: 148,
            fontWeight: 800,
            letterSpacing: 6,
            color: TEXT,
            transform: `scale(${0.86 + logo * 0.14})`,
            opacity: logo,
            position: 'relative',
            overflow: 'hidden',
          }}
        >
          XY-CtoPS5
          <div
            style={{
              position: 'absolute',
              top: 0,
              bottom: 0,
              width: 160,
              left: glint,
              background:
                'linear-gradient(90deg, transparent, rgba(255,255,255,0.42), transparent)',
              transform: 'skewX(-18deg)',
            }}
          />
        </div>
        <div style={{ ...sub, marginTop: 22, fontSize: 44, color: ACCENT, letterSpacing: 3 }}>
          键鼠玩 PS5
        </div>
        <div style={{ ...sub, marginTop: 14, fontSize: 26, color: DIM, letterSpacing: 1 }}>
          采集卡画面 · Remote Play 输入通道
        </div>
      </div>
      <Audio src={staticFile('voice/01_intro.wav')} />
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// 场景 2：原理示意图
// ---------------------------------------------------------------------------
const DiagramBox = ({
  x,
  y,
  label,
  sub,
  delay,
  color,
}: {
  x: number;
  y: number;
  label: string;
  sub: string;
  delay: number;
  color: string;
}) => {
  const frame = useCurrentFrame();
  const p = spring({ frame: frame - delay, fps: FPS, config: { damping: 200 }, durationInFrames: 18 });
  return (
    <div
      style={{
        position: 'absolute',
        left: x,
        top: y,
        width: 320,
        height: 190,
        background: PANEL,
        border: `2px solid ${color}`,
        borderRadius: 16,
        opacity: p,
        transform: `translateY(${(1 - p) * 40}px)`,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        fontFamily: 'Microsoft YaHei, sans-serif',
      }}
    >
      <div style={{ fontSize: 40, color: TEXT, fontWeight: 700 }}>{label}</div>
      <div style={{ fontSize: 20, color: DIM, marginTop: 10 }}>{sub}</div>
    </div>
  );
};

const Arrow = ({ x1, x2, y, delay, color, label }: { x1: number; x2: number; y: number; delay: number; color: string; label: string }) => {
  const frame = useCurrentFrame();
  const p = interpolate(frame, [delay, delay + 22], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return (
    <svg style={{ position: 'absolute', left: 0, top: 0, width: 1920, height: 1080, pointerEvents: 'none' }}>
      <line
        x1={x1}
        y1={y}
        x2={x1 + (x2 - x1) * p}
        y2={y}
        stroke={color}
        strokeWidth={4}
        strokeDasharray="10 8"
      />
      <text
        x={(x1 + x2) / 2}
        y={y - 18}
        fill={color}
        fontSize={22}
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
  const title = fadeUp(frame, 0, 18);
  return (
    <AbsoluteFill style={{ background: BG }}>
      <Grid />
      <div style={{ ...title, position: 'absolute', top: 80, width: '100%', textAlign: 'center' }}>
        <span style={{ fontSize: 52, color: TEXT, fontFamily: 'Microsoft YaHei, sans-serif', fontWeight: 700 }}>
          两路并行
        </span>
      </div>
      {/* 画面链路：PS5 → 采集卡 → 画面 */}
      <DiagramBox x={110} y={190} label="PS5" sub="游戏主机" delay={10} color={ACCENT} />
      <DiagramBox x={730} y={190} label="采集卡" sub="HDMI 环出·零延迟" delay={16} color={ACCENT2} />
      <DiagramBox x={1350} y={190} label="画面" sub="在 PC 上显示" delay={22} color={ACCENT2} />
      <Arrow x1={450} x2={710} y={285} delay={30} color={ACCENT2} label="HDMI 环出" />
      <Arrow x1={1070} x2={1330} y={285} delay={40} color={ACCENT2} label="采集画面" />
      {/* 输入链路：键鼠 → Remote Play → 手柄协议 */}
      <DiagramBox x={730} y={520} label="Remote Play" sub="输入通道" delay={60} color={ACCENT} />
      <DiagramBox x={1350} y={520} label="键鼠" sub="伪装成手柄" delay={66} color={ACCENT} />
      <Arrow x1={1070} x2={1330} y={615} delay={76} color={ACCENT} label="手柄协议" />
      <Cap text="画面：采集卡 / 输入：Remote Play" from={20} />
      <Audio src={staticFile('voice/02_diagram.wav')} />
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// 场景 3：鼠标手感（要点逐条入场）
// ---------------------------------------------------------------------------
const Bullet = ({ index, title, desc }: { index: number; title: string; desc: string }) => {
  const frame = useCurrentFrame();
  const start = index * 34 + 10;
  const p = spring({ frame: frame - start, fps: FPS, config: { damping: 200 }, durationInFrames: 16 });
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        marginBottom: 34,
        opacity: p,
        transform: `translateX(${(1 - p) * -30}px)`,
      }}
    >
      <div
        style={{
          width: 12,
          height: 12,
          background: ACCENT,
          borderRadius: 6,
          marginTop: 14,
          marginRight: 18,
          flexShrink: 0,
        }}
      />
      <div>
        <div style={{ fontSize: 40, color: TEXT, fontWeight: 700, fontFamily: 'Microsoft YaHei, sans-serif' }}>
          {title}
        </div>
        <div style={{ fontSize: 24, color: DIM, marginTop: 6, fontFamily: 'Microsoft YaHei, sans-serif' }}>
          {desc}
        </div>
      </div>
    </div>
  );
};

const SceneMouse: React.FC = () => {
  const frame = useCurrentFrame();
  const title = fadeUp(frame, 0, 18);
  return (
    <AbsoluteFill style={{ background: BG }}>
      <Grid />
      <div style={{ ...title, position: 'absolute', top: 100, width: '100%', textAlign: 'center' }}>
        <span style={{ fontSize: 52, color: TEXT, fontFamily: 'Microsoft YaHei, sans-serif', fontWeight: 700 }}>
          鼠标 → 右摇杆
        </span>
      </div>
      <div style={{ position: 'absolute', left: 260, top: 230 }}>
        <Bullet index={0} title="Raw Input 设备位移" desc="直接读鼠标报文，不依赖光标位置" />
        <Bullet index={1} title="反死区 Anti-Deadzone" desc="小移动抬升，跳过游戏自身的摇杆死区" />
        <Bullet index={2} title="两段灵敏度" desc="慢转瞄准精细，快转转身跟手" />
        <Bullet index={3} title="Flick Stick" desc="快速甩动瞬间转身" />
      </div>
      <Cap text="照着业界成熟方案实现" from={16} />
      <Audio src={staticFile('voice/03_mouse.wav')} />
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// 场景 4：其他功能
// ---------------------------------------------------------------------------
const Feat = ({ x, y, icon, title, desc, delay }: { x: number; y: number; icon: string; title: string; desc: string; delay: number }) => {
  const frame = useCurrentFrame();
  const p = spring({ frame: frame - delay, fps: FPS, config: { damping: 200 }, durationInFrames: 16 });
  return (
    <div
      style={{
        position: 'absolute',
        left: x,
        top: y,
        width: 460,
        opacity: p,
        transform: `translateY(${(1 - p) * 30}px)`,
        fontFamily: 'Microsoft YaHei, sans-serif',
      }}
    >
      <div style={{ fontSize: 64 }}>{icon}</div>
      <div style={{ fontSize: 38, color: TEXT, fontWeight: 700, marginTop: 12 }}>{title}</div>
      <div style={{ fontSize: 22, color: DIM, marginTop: 8, lineHeight: 1.5 }}>{desc}</div>
    </div>
  );
};

const SceneFeatures: React.FC = () => {
  const frame = useCurrentFrame();
  const title = fadeUp(frame, 0, 18);
  return (
    <AbsoluteFill style={{ background: BG }}>
      <Grid />
      <div style={{ ...title, position: 'absolute', top: 90, width: '100%', textAlign: 'center' }}>
        <span style={{ fontSize: 52, color: TEXT, fontFamily: 'Microsoft YaHei, sans-serif', fontWeight: 700 }}>
          完整功能
        </span>
      </div>
      <Feat x={180} y={260} icon="🎮" title="多套按键映射" desc="每个模式一套键位，一个键循环切换" delay={8} />
      <Feat x={760} y={260} icon="🎚️" title="扳机深度可调" desc="L2 / R2 按设定深度输出" delay={22} />
      <Feat x={1340} y={260} icon="⚡" title="参数实时生效" desc="滑条即调即用，松手保存" delay={36} />
      <Audio src={staticFile('voice/04_features.wav')} />
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// 场景 5：结尾（GitHub）
// ---------------------------------------------------------------------------
const SceneOutro: React.FC = () => {
  const frame = useCurrentFrame();
  const logo = spring({ frame, fps: FPS, config: { damping: 200 }, durationInFrames: 26 });
  const info = fadeUp(frame, 26, 20);
  return (
    <AbsoluteFill style={{ background: BG }}>
      <Grid />
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
            fontSize: 96,
            fontWeight: 800,
            color: TEXT,
            letterSpacing: 4,
            opacity: logo,
            transform: `scale(${0.9 + logo * 0.1})`,
          }}
        >
          XY-CtoPS5
        </div>
        <div style={{ ...info, marginTop: 30, fontSize: 40, color: ACCENT }}>
          GitHub 开源 · GPL-3.0
        </div>
        <div style={{ ...info, marginTop: 16, fontSize: 26, color: DIM }}>
          下载安装程序，即可用键鼠玩 PS5
        </div>
        <div style={{ ...info, marginTop: 40, fontSize: 22, color: DIM, opacity: 0.7 }}>
          采集卡 + Remote Play 输入通道 · 仅建议单人单机游戏
        </div>
      </div>
      <Audio src={staticFile('voice/05_outro.wav')} />
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// 主时间轴
// ---------------------------------------------------------------------------
const ShotWithSequence: React.FC<{ from: number; duration: number; children: React.ReactNode }> = ({
  from,
  duration,
  children,
}) => (
  <Sequence from={from} durationInFrames={duration}>
    {children}
  </Sequence>
);

const SHOT_COMPONENTS: { key: keyof typeof PS5_SHOTS; comp: React.ReactNode }[] = [
  { key: 'intro', comp: <SceneIntro /> },
  { key: 'diagram', comp: <SceneDiagram /> },
  { key: 'mouse', comp: <SceneMouse /> },
  { key: 'features', comp: <SceneFeatures /> },
  { key: 'outro', comp: <SceneOutro /> },
];

export const Ps5Main: React.FC = () => (
  <AbsoluteFill style={{ background: BG }}>
    {SHOT_COMPONENTS.map(({ key, comp }) => {
      const shot = PS5_SHOTS[key];
      return (
        <ShotWithSequence key={key} from={shot.from} duration={shot.duration}>
          {comp}
        </ShotWithSequence>
      );
    })}
  </AbsoluteFill>
);
