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
// XY-CtoPS5 介绍 + 教程片 — 高级暗色科技风
// 1920x1080 @ 30fps
// 结构：品牌开场 → 原理 → 鼠标算法 → 功能 → 连接教程 → 映射教程 → 运行教程 → 结尾
// ============================================================================

const BG_DEEP = '#05070b';
const TEXT = '#e8eef7';
const DIM = '#8394aa';
const ACCENT = '#4da3ff';
const ACCENT2 = '#7ee787';
const GOLD = '#e8b45a';

const FPS = 30;

// 场景时长按每段旁白的实际长度分配（edge-tts 约 48kbps，按文件大小估算 + 30 帧余量）
const S = {
  intro: { from: 0, duration: 246 },
  diagram: { from: 246, duration: 324 },
  mouse: { from: 570, duration: 456 },
  features: { from: 1026, duration: 321 },
  connect1: { from: 1347, duration: 465 },
  connect2: { from: 1812, duration: 636 },
  mapping1: { from: 2448, duration: 459 },
  mapping2: { from: 2907, duration: 615 },
  run1: { from: 3522, duration: 500 },
  run2: { from: 4022, duration: 450 },
  run3: { from: 4472, duration: 370 },
  run4: { from: 4842, duration: 336 },
  outro: { from: 5178, duration: 234 },
} as const;

export const PS5_TOTAL = 5412;

// ---------------------------------------------------------------------------
// 高级背景：径向辉光 + 透视网格 + 扫描线 + 暗角
// ---------------------------------------------------------------------------
const Backdrop: React.FC<{ accent?: string }> = ({ accent = ACCENT }) => {
  const frame = useCurrentFrame();
  const drift = Math.sin(frame / 100) * 24;
  const scan = (frame * 3.2) % 1200;
  return (
    <AbsoluteFill style={{ background: BG_DEEP, overflow: 'hidden' }}>
      {/* 主辉光 */}
      <div
        style={{
          position: 'absolute',
          width: 1400,
          height: 1400,
          left: '50%',
          top: '42%',
          transform: `translate(-50%, -50%) translateY(${drift}px)`,
          background: `radial-gradient(circle, ${accent}26, transparent 62%)`,
          filter: 'blur(30px)',
        }}
      />
      {/* 透视网格 */}
      <div
        style={{
          position: 'absolute',
          inset: -200,
          backgroundImage:
            'linear-gradient(rgba(120,160,220,0.055) 1px, transparent 1px), linear-gradient(90deg, rgba(120,160,220,0.055) 1px, transparent 1px)',
          backgroundSize: '72px 72px',
          transform: `perspective(900px) rotateX(62deg) translateY(${(frame * 0.4) % 72 - 72}px)`,
          transformOrigin: 'center 100%',
          maskImage: 'linear-gradient(to top, black 0%, transparent 72%)',
          WebkitMaskImage: 'linear-gradient(to top, black 0%, transparent 72%)',
        }}
      />
      {/* 扫描线 */}
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          height: 1.5,
          top: scan,
          background: `linear-gradient(90deg, transparent, ${accent}66, transparent)`,
          opacity: 0.5,
        }}
      />
      {/* 暗角 */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background:
            'radial-gradient(ellipse at center, transparent 48%, rgba(0,0,0,0.55) 100%)',
        }}
      />
    </AbsoluteFill>
  );
};

// 装饰：旋转光环
const Halo: React.FC<{ size?: number; opacity?: number }> = ({
  size = 900,
  opacity = 0.18,
}) => {
  const frame = useCurrentFrame();
  return (
    <div
      style={{
        position: 'absolute',
        width: size,
        height: size,
        left: '50%',
        top: '50%',
        transform: `translate(-50%,-50%) rotate(${frame * 0.3}deg)`,
        border: `1px solid ${ACCENT}${Math.round(opacity * 255).toString(16).padStart(2, '0')}`,
        borderRadius: '50%',
        boxShadow: `0 0 60px ${ACCENT}22 inset`,
      }}
    />
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
        bottom: 72,
        width: '100%',
        textAlign: 'center',
        opacity: p,
        color: DIM,
        fontSize: 28,
        letterSpacing: 3,
        fontFamily: 'Microsoft YaHei, sans-serif',
      }}
    >
      {text}
    </div>
  );
};

// ---------------------------------------------------------------------------
// 开场：字标遮罩揭示 + 字距收敛 + 扫光
// ---------------------------------------------------------------------------
const SceneIntro: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const reveal = interpolate(frame, [6, 46], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const spacing = interpolate(frame, [6, 52], [64, 6], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const glow = interpolate(frame, [30, 80], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const sub = spring({ frame: frame - 46, fps, config: { damping: 200 }, durationInFrames: 24 });
  const glint = interpolate(frame, [50, 110], [-300, 2200], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill>
      <Backdrop />
      <Halo size={1100} opacity={0.12} />
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
            fontSize: 150,
            fontWeight: 800,
            letterSpacing: spacing,
            color: TEXT,
            clipPath: `inset(0 ${(1 - reveal) * 100}% 0 0)`,
            overflow: 'hidden',
            textShadow: `0 0 ${40 * glow}px ${ACCENT}66`,
          }}
        >
          XY-CtoPS5
          <div
            style={{
              position: 'absolute',
              top: 0,
              bottom: 0,
              width: 140,
              left: glint,
              background:
                'linear-gradient(90deg, transparent, rgba(255,255,255,0.5), transparent)',
              transform: 'skewX(-16deg)',
            }}
          />
        </div>
        <div
          style={{
            marginTop: 26,
            fontSize: 46,
            letterSpacing: 10,
            color: ACCENT,
            opacity: sub,
            transform: `translateY(${(1 - sub) * 20}px)`,
          }}
        >
          键鼠玩 PS5
        </div>
        <div
          style={{
            marginTop: 14,
            fontSize: 24,
            letterSpacing: 4,
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
  const p = spring({ frame: frame - delay, fps: FPS, config: { damping: 200 }, durationInFrames: 20 });
  return (
    <div
      style={{
        position: 'absolute',
        left: x,
        top: y,
        width: 300,
        height: 170,
        borderRadius: 18,
        background: 'rgba(14,20,30,0.85)',
        border: `1.5px solid ${color}88`,
        boxShadow: `0 24px 60px rgba(0,0,0,0.55), 0 0 30px ${color}22`,
        opacity: p,
        transform: `translateY(${(1 - p) * 36}px) scale(${0.94 + p * 0.06})`,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        fontFamily: 'Microsoft YaHei, sans-serif',
        backdropFilter: 'blur(4px)',
      }}
    >
      <div style={{ fontSize: 38, color: TEXT, fontWeight: 700 }}>{label}</div>
      <div style={{ fontSize: 18, color: DIM, marginTop: 8 }}>{sub}</div>
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
  const p = interpolate(frame, [delay, delay + 24], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return (
    <svg style={{ position: 'absolute', left: 0, top: 0, width: 1920, height: 1080 }}>
      <defs>
        <linearGradient id={`g-${x1}-${y}`} x1="0" x2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.1" />
          <stop offset="100%" stopColor={color} stopOpacity="0.9" />
        </linearGradient>
      </defs>
      <line
        x1={x1}
        y1={y}
        x2={x1 + (x2 - x1) * p}
        y2={y}
        stroke={`url(#g-${x1}-${y})`}
        strokeWidth={3}
        strokeDasharray="8 6"
      />
      <text
        x={(x1 + x2) / 2}
        y={y - 16}
        fill={color}
        fontSize={20}
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
  const title = interpolate(frame, [0, 20], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return (
    <AbsoluteFill>
      <Backdrop />
      <div
        style={{
          position: 'absolute',
          top: 74,
          width: '100%',
          textAlign: 'center',
          opacity: title,
          transform: `translateY(${(1 - title) * 20}px)`,
        }}
      >
        <span style={{ fontSize: 50, color: TEXT, fontFamily: 'Microsoft YaHei, sans-serif', fontWeight: 700, letterSpacing: 4 }}>
          两路并行
        </span>
      </div>
      <NodeCard x={110} y={195} label="PS5" sub="游戏主机" delay={8} color={ACCENT} />
      <NodeCard x={720} y={195} label="采集卡" sub="HDMI 环出 · 零延迟" delay={16} color={ACCENT2} />
      <NodeCard x={1330} y={195} label="画面" sub="PC 上显示" delay={24} color={ACCENT2} />
      <FlowLine x1={430} x2={700} y={285} delay={30} color={ACCENT2} label="HDMI" />
      <FlowLine x1={1040} x2={1310} y={285} delay={40} color={ACCENT2} label="采集" />
      <NodeCard x={720} y={530} label="Remote Play" sub="输入通道" delay={64} color={ACCENT} />
      <NodeCard x={1330} y={530} label="键鼠" sub="伪装成手柄" delay={72} color={ACCENT} />
      <FlowLine x1={1040} x2={1310} y={620} delay={82} color={ACCENT} label="手柄协议" />
      <Cap text="画面：采集卡 / 输入：Remote Play" from={24} />
      <Audio src={staticFile('voice/02_diagram.mp3')} />
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// 要点列表（鼠标算法 / 功能）
// ---------------------------------------------------------------------------
const Bullet: React.FC<{ index: number; title: string; desc: string; color?: string }> = ({
  index,
  title,
  desc,
  color = ACCENT,
}) => {
  const frame = useCurrentFrame();
  const start = index * 32 + 8;
  const p = spring({ frame: frame - start, fps: FPS, config: { damping: 200 }, durationInFrames: 18 });
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        marginBottom: 32,
        opacity: p,
        transform: `translateX(${(1 - p) * -40}px)`,
      }}
    >
      <div
        style={{
          width: 10,
          height: 10,
          marginTop: 15,
          marginRight: 20,
          background: color,
          borderRadius: 5,
          boxShadow: `0 0 14px ${color}`,
          flexShrink: 0,
        }}
      />
      <div>
        <div style={{ fontSize: 38, color: TEXT, fontWeight: 700, fontFamily: 'Microsoft YaHei, sans-serif' }}>
          {title}
        </div>
        <div style={{ fontSize: 22, color: DIM, marginTop: 6, fontFamily: 'Microsoft YaHei, sans-serif' }}>
          {desc}
        </div>
      </div>
    </div>
  );
};

const SceneMouse: React.FC = () => {
  const frame = useCurrentFrame();
  const title = interpolate(frame, [0, 18], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return (
    <AbsoluteFill>
      <Backdrop accent={GOLD} />
      <div style={{ position: 'absolute', top: 88, width: '100%', textAlign: 'center', opacity: title }}>
        <span style={{ fontSize: 50, color: TEXT, fontFamily: 'Microsoft YaHei, sans-serif', fontWeight: 700, letterSpacing: 3 }}>
          鼠标 → 右摇杆
        </span>
      </div>
      <div style={{ position: 'absolute', left: 240, top: 210 }}>
        <Bullet index={0} title="Raw Input 设备位移" desc="直接读鼠标报文，不依赖光标位置" color={GOLD} />
        <Bullet index={1} title="反死区 Anti-Deadzone" desc="小移动抬升，跳过游戏自身的摇杆死区" color={GOLD} />
        <Bullet index={2} title="两段灵敏度" desc="慢转瞄准精细，快转转身跟手" color={GOLD} />
        <Bullet index={3} title="Flick Stick" desc="快速甩动瞬间转身" color={GOLD} />
      </div>
      <Cap text="照着业界成熟方案实现" from={18} />
      <Audio src={staticFile('voice/03_mouse.mp3')} />
    </AbsoluteFill>
  );
};

const Feat: React.FC<{ x: number; icon: string; title: string; desc: string; delay: number }> = ({
  x,
  icon,
  title,
  desc,
  delay,
}) => {
  const frame = useCurrentFrame();
  const p = spring({ frame: frame - delay, fps: FPS, config: { damping: 200 }, durationInFrames: 18 });
  return (
    <div
      style={{
        position: 'absolute',
        left: x,
        top: 300,
        width: 440,
        opacity: p,
        transform: `translateY(${(1 - p) * 36}px)`,
        fontFamily: 'Microsoft YaHei, sans-serif',
        textAlign: 'center',
      }}
    >
      <div style={{ fontSize: 58 }}>{icon}</div>
      <div style={{ fontSize: 34, color: TEXT, fontWeight: 700, marginTop: 14 }}>{title}</div>
      <div style={{ fontSize: 20, color: DIM, marginTop: 8, lineHeight: 1.5 }}>{desc}</div>
    </div>
  );
};

const SceneFeatures: React.FC = () => {
  return (
    <AbsoluteFill>
      <Backdrop accent={ACCENT2} />
      <div style={{ position: 'absolute', top: 100, width: '100%', textAlign: 'center' }}>
        <span style={{ fontSize: 50, color: TEXT, fontFamily: 'Microsoft YaHei, sans-serif', fontWeight: 700, letterSpacing: 3 }}>
          完整功能
        </span>
      </div>
      <Feat x={130} icon="🎮" title="多套按键映射" desc="每个模式一套键位，一个键循环切换" delay={6} />
      <Feat x={730} icon="🎚️" title="扳机深度可调" desc="L2 / R2 按设定深度输出" delay={18} />
      <Feat x={1330} icon="⚡" title="参数实时生效" desc="滑条即调即用，松手保存" delay={30} />
      <Audio src={staticFile('voice/04_features.mp3')} />
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// 截图讲解：3D 悬浮卡片 + 缩放 + 高亮框 + 标注
// ---------------------------------------------------------------------------
type Callout = {
  x: number; // 相对图片宽度的百分比 0-1
  y: number;
  w: number;
  h: number;
  label: string;
  delay: number;
};

const ScreenshotShot: React.FC<{
  image: string;
  title: string;
  voice: string;
  callouts?: Callout[];
  zoomFrom?: number;
  zoomTo?: number;
  tilt?: boolean;
}> = ({ image, title, voice, callouts = [], zoomFrom = 0.98, zoomTo = 1.06, tilt = true }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = spring({ frame, fps, config: { damping: 200 }, durationInFrames: 26 });
  const zoom = interpolate(frame, [0, 400], [zoomFrom, zoomTo], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const tiltY = tilt ? interpolate(enter, [0, 1], [-6, 0]) : 0;
  const titleP = interpolate(frame, [30, 50], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  // 图片在画面中的尺寸（保持 1432x1196 比例，高度留出标题和字幕）
  const imgH = 820;
  const imgW = (1432 / 1196) * imgH;
  const imgLeft = (1920 - imgW) / 2;
  const imgTop = 120;

  return (
    <AbsoluteFill>
      <Backdrop />
      <div
        style={{
          position: 'absolute',
          top: 42,
          width: '100%',
          textAlign: 'center',
          opacity: titleP,
          transform: `translateY(${(1 - titleP) * -14}px)`,
        }}
      >
        <span
          style={{
            fontSize: 44,
            color: TEXT,
            fontFamily: 'Microsoft YaHei, sans-serif',
            fontWeight: 700,
            letterSpacing: 4,
            textShadow: `0 0 30px ${ACCENT}44`,
          }}
        >
          {title}
        </span>
      </div>

      {/* 截图卡片：悬浮 + 倾斜 + 辉光 */}
      <div
        style={{
          position: 'absolute',
          left: imgLeft,
          top: imgTop,
          width: imgW,
          height: imgH,
          perspective: 1600,
          opacity: enter,
          transform: `translateY(${(1 - enter) * 60}px)`,
        }}
      >
        <div
          style={{
            width: '100%',
            height: '100%',
            transform: `rotateY(${tiltY}deg) scale(${zoom})`,
            borderRadius: 14,
            overflow: 'hidden',
            border: '1px solid rgba(120,160,220,0.28)',
            boxShadow: `0 50px 120px rgba(0,0,0,0.7), 0 0 60px ${ACCENT}1f`,
          }}
        >
          <Img
            src={staticFile(image)}
            style={{ width: '100%', height: '100%', objectFit: 'cover' }}
          />
        </div>

        {/* 高亮标注框 */}
        {callouts.map((c, i) => {
          const p = interpolate(frame, [c.delay, c.delay + 16], [0, 1], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
          });
          const pulse = 0.6 + 0.4 * Math.sin((frame - c.delay) / 10);
          return (
            <React.Fragment key={i}>
              <div
                style={{
                  position: 'absolute',
                  left: `${c.x * 100}%`,
                  top: `${c.y * 100}%`,
                  width: `${c.w * 100}%`,
                  height: `${c.h * 100}%`,
                  border: `2px solid ${ACCENT}`,
                  borderRadius: 8,
                  boxShadow: `0 0 ${18 + pulse * 14}px ${ACCENT}aa, inset 0 0 18px ${ACCENT}22`,
                  opacity: p,
                  pointerEvents: 'none',
                }}
              />
              <div
                style={{
                  position: 'absolute',
                  left: `${c.x * 100}%`,
                  top: `calc(${c.y * 100}% - 34px)`,
                  color: ACCENT,
                  fontSize: 19,
                  fontFamily: 'Microsoft YaHei, sans-serif',
                  opacity: p,
                  transform: `translateX(${(1 - p) * 12}px)`,
                  whiteSpace: 'nowrap',
                  background: 'rgba(5,7,11,0.9)',
                  padding: '3px 10px',
                  borderRadius: 6,
                  border: `1px solid ${ACCENT}55`,
                }}
              >
                {c.label}
              </div>
            </React.Fragment>
          );
        })}
      </div>
      <Audio src={staticFile(voice)} />
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// 文字讲解（无截图场景）
// ---------------------------------------------------------------------------
const TextShot: React.FC<{
  title: string;
  voice: string;
  items: { emoji: string; title: string; desc: string }[];
}> = ({ title, voice, items }) => {
  const frame = useCurrentFrame();
  const titleP = interpolate(frame, [0, 18], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return (
    <AbsoluteFill>
      <Backdrop />
      <div style={{ position: 'absolute', top: 88, width: '100%', textAlign: 'center', opacity: titleP }}>
        <span
          style={{
            fontSize: 48,
            color: TEXT,
            fontFamily: 'Microsoft YaHei, sans-serif',
            fontWeight: 700,
            letterSpacing: 3,
            textShadow: `0 0 30px ${ACCENT}44`,
          }}
        >
          {title}
        </span>
      </div>
      <div style={{ position: 'absolute', left: 250, top: 230 }}>
        {items.map((item, i) => {
          const p = spring({ frame: frame - i * 26 - 10, fps: FPS, config: { damping: 200 }, durationInFrames: 18 });
          return (
            <div
              key={i}
              style={{
                display: 'flex',
                alignItems: 'flex-start',
                marginBottom: 38,
                opacity: p,
                transform: `translateX(${(1 - p) * -40}px)`,
              }}
            >
              <div style={{ fontSize: 42, marginRight: 24, width: 64 }}>{item.emoji}</div>
              <div>
                <div style={{ fontSize: 36, color: TEXT, fontWeight: 700, fontFamily: 'Microsoft YaHei, sans-serif' }}>
                  {item.title}
                </div>
                <div style={{ fontSize: 21, color: DIM, marginTop: 6, fontFamily: 'Microsoft YaHei, sans-serif' }}>
                  {item.desc}
                </div>
              </div>
            </div>
          );
        })}
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
  const info = interpolate(frame, [30, 54], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return (
    <AbsoluteFill>
      <Backdrop />
      <Halo size={900} opacity={0.14} />
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
            fontSize: 100,
            fontWeight: 800,
            letterSpacing: 6,
            color: TEXT,
            opacity: logo,
            transform: `scale(${0.9 + logo * 0.1})`,
            textShadow: `0 0 50px ${ACCENT}55`,
          }}
        >
          XY-CtoPS5
        </div>
        <div style={{ marginTop: 34, fontSize: 40, color: ACCENT, opacity: info, letterSpacing: 3 }}>
          GitHub 开源 · GPL-3.0
        </div>
        <div style={{ marginTop: 16, fontSize: 26, color: DIM, opacity: info, letterSpacing: 2 }}>
          一个安装程序，就能用键鼠玩 PS5
        </div>
        <div style={{ marginTop: 46, fontSize: 20, color: DIM, opacity: info * 0.65 }}>
          采集卡 + Remote Play 输入通道 · 仅建议单人单机游戏
        </div>
      </div>
      <Audio src={staticFile('voice/05_outro.mp3')} />
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// 时间轴
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
  { key: 'mouse', comp: <SceneMouse /> },
  { key: 'features', comp: <SceneFeatures /> },
  {
    key: 'connect1',
    comp: (
      <ScreenshotShot
        image="images/connect-offline-fallback.png"
        title="连接 · 第一次配对"
        voice="voice/06_connect.mp3"
        callouts={[
          { x: 0.27, y: 0.30, w: 0.70, h: 0.29, label: '主机：填 PS5 IP / 扫描局域网', delay: 40 },
          { x: 0.27, y: 0.66, w: 0.70, h: 0.20, label: '配对：Account ID + 8 位 PIN', delay: 130 },
          { x: 0.27, y: 0.925, w: 0.18, h: 0.04, label: '连接主机', delay: 200 },
        ]}
        zoomFrom={0.96}
        zoomTo={1.03}
      />
    ),
  },
  {
    key: 'connect2',
    comp: (
      <ScreenshotShot
        image="images/connect-quick.png"
        title="连接 · 已配对直接连"
        voice="voice/07_connect2.mp3"
        callouts={[
          { x: 0.27, y: 0.16, w: 0.70, h: 0.20, label: '已配对主机 · 自动检测', delay: 60 },
          { x: 0.28, y: 0.40, w: 0.17, h: 0.04, label: '直接连接', delay: 140 },
          { x: 0.69, y: 0.40, w: 0.13, h: 0.04, label: '换 ID / 重新配对', delay: 210 },
        ]}
        zoomFrom={1.04}
        zoomTo={0.98}
      />
    ),
  },
  {
    key: 'mapping1',
    comp: (
      <ScreenshotShot
        image="images/mapping-page.png"
        title="映射 · 预设与模式"
        voice="voice/08_mapping.mp3"
        callouts={[
          { x: 0.27, y: 0.15, w: 0.70, h: 0.20, label: '预设 = 一整套按键', delay: 40 },
          { x: 0.27, y: 0.31, w: 0.70, h: 0.05, label: '模式 · 切换键循环', delay: 110 },
        ]}
        zoomFrom={0.97}
        zoomTo={1.04}
      />
    ),
  },
  {
    key: 'mapping2',
    comp: (
      <ScreenshotShot
        image="images/mapping-page.png"
        title="映射 · 按键列表"
        voice="voice/09_mapping2.mp3"
        callouts={[
          { x: 0.27, y: 0.38, w: 0.70, h: 0.24, label: '改键 / 编辑 / 删除', delay: 50 },
          { x: 0.27, y: 0.71, w: 0.70, h: 0.04, label: '左摇杆方向键', delay: 150 },
        ]}
        zoomFrom={1.05}
        zoomTo={0.99}
      />
    ),
  },
  {
    key: 'run1',
    comp: (
      <ScreenshotShot
        image="images/run-page-real.png"
        title="运行 · 开始捕获"
        voice="voice/10_run.mp3"
        callouts={[
          { x: 0.28, y: 0.73, w: 0.68, h: 0.035, label: '① 先选捕获时切到的窗口', delay: 40 },
          { x: 0.286, y: 0.286, w: 0.168, h: 0.042, label: '② 再点开始捕获', delay: 150 },
        ]}
        zoomFrom={0.97}
        zoomTo={1.03}
      />
    ),
  },
  {
    key: 'run2',
    comp: (
      <ScreenshotShot
        image="images/run-page-real.png"
        title="运行 · 鼠标手感"
        voice="voice/11_run2.mp3"
        callouts={[
          { x: 0.28, y: 0.37, w: 0.68, h: 0.15, label: '过渡 / 死区 / 灵敏度 / 慢灵敏 / 快灵敏 / 平滑', delay: 40 },
          { x: 0.28, y: 0.53, w: 0.68, h: 0.04, label: '曲线 · 鼠标视角 · Flick Stick', delay: 140 },
        ]}
        zoomFrom={1.04}
        zoomTo={0.98}
      />
    ),
  },
  {
    key: 'run3',
    comp: (
      <ScreenshotShot
        image="images/run-page-real.png"
        title="运行 · 扳机与窗口"
        voice="voice/12_run3.mp3"
        callouts={[
          { x: 0.28, y: 0.61, w: 0.68, h: 0.12, label: 'R2 / L2 深度 · 加深减浅键', delay: 40 },
        ]}
        zoomFrom={0.98}
        zoomTo={1.04}
      />
    ),
  },
  {
    key: 'run4',
    comp: (
      <ScreenshotShot
        image="images/connect-connected.png"
        title="全部调好 · 按 F8 开始"
        voice="voice/13_run4.mp3"
        callouts={[{ x: 0.27, y: 0.55, w: 0.70, h: 0.18, label: '下一步：切到运行页', delay: 40 }]}
        zoomFrom={0.97}
        zoomTo={1.03}
      />
    ),
  },
  { key: 'outro', comp: <SceneOutro /> },
];

// 背景音乐与音效
const Bgm: React.FC = () => (
  <Audio
    src={staticFile('audio/bgm-tech-house.mp3')}
    volume={(f) =>
      interpolate(
        f,
        [0, 20, 5180, 5412],
        [0, 0.16, 0.16, 0],
        { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' },
      )
    }
  />
);

const SFX_DEFS = [
  { from: 24, src: 'impact-cine.mp3', volume: 0.5 },
  { from: 30, src: 'sparkle.mp3', volume: 0.32 },
  { from: 238, src: 'whoosh-fast.mp3', volume: 0.42 },
  { from: 562, src: 'transition-snap.mp3', volume: 0.42 },
  { from: 1018, src: 'whoosh-fast.mp3', volume: 0.42 },
  { from: 1339, src: 'whoosh-big.mp3', volume: 0.4 },
  { from: 1804, src: 'transition-soft.mp3', volume: 0.35 },
  { from: 2440, src: 'whoosh-fast.mp3', volume: 0.42 },
  { from: 2899, src: 'transition-snap.mp3', volume: 0.4 },
  { from: 3514, src: 'whoosh-big.mp3', volume: 0.4 },
  { from: 4014, src: 'transition-soft.mp3', volume: 0.35 },
  { from: 4464, src: 'whoosh-fast.mp3', volume: 0.4 },
  { from: 4834, src: 'transition-soft.mp3', volume: 0.35 },
  { from: 5158, src: 'riser-cine.mp3', volume: 0.5 },
  { from: 5238, src: 'impact-cine.mp3', volume: 0.55 },
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
  <AbsoluteFill style={{ background: BG_DEEP }}>
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
