// 检查成片：时长、音轨、视频轨是否都在，避免「渲染成功但音轨丢了」
import {parseMedia} from '@remotion/media-parser';
import {nodeReader} from '@remotion/media-parser/node';
import {stat} from 'node:fs/promises';
import path from 'node:path';

const src = path.resolve('out/promo.mp4');
const size = (await stat(src)).size;
const info = await parseMedia({
  src,
  fields: {durationInSeconds: true, tracks: true, dimensions: true, fps: true, videoCodec: true, audioCodec: true},
  reader: nodeReader,
  acknowledgeRemotionLicense: true,
});

const tracks = info.tracks ?? [];
console.log('文件        ', src);
console.log('大小        ', (size / 1024 / 1024).toFixed(1), 'MB');
console.log('时长        ', info.durationInSeconds?.toFixed(2), 's =', Math.round((info.durationInSeconds ?? 0) * 30), 'f');
console.log('画面        ', `${info.dimensions?.width}x${info.dimensions?.height}`, '@', info.fps, 'fps');
console.log('编码        ', info.videoCodec, '/', info.audioCodec);
console.log('轨道        ', tracks.map((t) => t.type).join(', '));

const hasAudio = tracks.some((t) => t.type === 'audio');
const hasVideo = tracks.some((t) => t.type === 'video');
if (!hasAudio || !hasVideo) {
  console.error('\n缺轨：视频或音频没写进成片');
  process.exit(1);
}
const expected = 6232 / 30;
if (Math.abs((info.durationInSeconds ?? 0) - expected) > 0.5) {
  console.error(`\n时长不符：期望 ${expected.toFixed(2)}s`);
  process.exit(1);
}
console.log('\n成片完整：6077+ 帧画面 + 音轨都在，时长与时间轴一致。');
