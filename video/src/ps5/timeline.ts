// 视频时间轴：唯一事实来源。
//
// 历史教训：上一版按「mp3 文件大小 ÷ 48kbps」估算时长，实际码率不符，
// 导致几乎每一段旁白都被 Sequence 硬切（用户反馈「话没说完截断了」）。
// 现在 voice 帧数由 measure-audio.mjs 实测（@remotion/media-parser 读真实时长 × 30fps 向上取整），
// 并在这里做构建期自检：任何一段 duration 小于「音频帧数 + 10」，直接抛错。

export type SegmentKey =
  | 'intro'
  | 'diagram'
  | 'modes'
  | 'connect1'
  | 'connect2'
  | 'mapping1'
  | 'mapping2'
  | 'controller'
  | 'run1'
  | 'run2'
  | 'run3'
  | 'gta6a'
  | 'gta6b'
  | 'outro';

type Segment = {
  voice: number; // 旁白实测帧数（30fps）
  duration: number; // 本段总帧数 = 旁白 + 呼吸余量
  audio: string; // public/ 下的相对路径
};

const SEGMENTS: Record<SegmentKey, Segment> = {
  intro: { voice: 327, duration: 360, audio: 'voice/01_intro.mp3' },
  diagram: { voice: 301, duration: 335, audio: 'voice/02_diagram.mp3' },
  modes: { voice: 479, duration: 515, audio: 'voice/03_modes.mp3' },
  connect1: { voice: 447, duration: 482, audio: 'voice/06_connect.mp3' },
  connect2: { voice: 620, duration: 656, audio: 'voice/07_connect2.mp3' },
  mapping1: { voice: 439, duration: 474, audio: 'voice/08_mapping.mp3' },
  mapping2: { voice: 600, duration: 636, audio: 'voice/09_mapping2.mp3' },
  controller: { voice: 415, duration: 450, audio: 'voice/08_controller.mp3' },
  run1: { voice: 512, duration: 548, audio: 'voice/10_run.mp3' },
  run2: { voice: 432, duration: 468, audio: 'voice/11_run2.mp3' },
  run3: { voice: 342, duration: 378, audio: 'voice/12_run3.mp3' },
  gta6a: { voice: 198, duration: 320, audio: 'voice/12_gta6_1.mp3' },
  gta6b: { voice: 200, duration: 320, audio: 'voice/13_gta6_2.mp3' },
  outro: { voice: 213, duration: 290, audio: 'voice/05_outro.mp3' },
};

export const ORDER: SegmentKey[] = [
  'intro',
  'diagram',
  'modes',
  'connect1',
  'connect2',
  'mapping1',
  'mapping2',
  'controller',
  'run1',
  'run2',
  'run3',
  'gta6a',
  'gta6b',
  'outro',
];

/** 每段至少留 10 帧余量，否则就是「旁白被切」。构建期直接拦。 */
const MIN_TAIL = 10;

const buildTimeline = () => {
  const spans = {} as Record<SegmentKey, { from: number; duration: number }>;
  let cursor = 0;
  for (const key of ORDER) {
    const seg = SEGMENTS[key];
    if (seg.duration < seg.voice + MIN_TAIL) {
      throw new Error(
        `[timeline] 段 "${key}" 时长 ${seg.duration}f 不足以容纳旁白 ${seg.voice}f + 余量 ${MIN_TAIL}f`,
      );
    }
    spans[key] = { from: cursor, duration: seg.duration };
    cursor += seg.duration;
  }
  return { spans, total: cursor };
};

const built = buildTimeline();

export const S = built.spans;
export const PS5_TOTAL = built.total;
export const VOICE_OF = (key: SegmentKey) => SEGMENTS[key].audio;
export const VOICE_FRAMES = (key: SegmentKey) => SEGMENTS[key].voice;
