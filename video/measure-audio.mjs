// 测量 public/voice 下所有旁白 mp3 的真实时长（帧精度，30fps）
// 用途：排时间轴时必须拿到精确秒数，之前按文件大小估算导致旁白被截断
import {parseMedia} from '@remotion/media-parser';
import {nodeReader} from '@remotion/media-parser/node';
import {readdir} from 'node:fs/promises';
import path from 'node:path';

const FPS = 30;
const dir = path.resolve('public/voice');
const files = (await readdir(dir)).filter((f) => f.endsWith('.mp3')).sort();

const rows = [];
for (const f of files) {
  const {durationInSeconds: duration} = await parseMedia({
    src: path.join(dir, f),
    fields: {durationInSeconds: true},
    reader: nodeReader,
    acknowledgeRemotionLicense: true,
  });
  const frames = Math.ceil((duration ?? 0) * FPS);
  rows.push({file: f, seconds: Number((duration ?? 0).toFixed(2)), frames});
}

console.log('file'.padEnd(22), 'seconds'.padStart(8), 'frames(+30余量)'.padStart(16));
for (const r of rows) {
  console.log(r.file.padEnd(22), String(r.seconds).padStart(8), String(r.frames).padStart(16));
}
console.log('\nJSON:');
console.log(JSON.stringify(rows, null, 0));
