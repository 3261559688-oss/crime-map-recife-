#!/usr/bin/env node
/**
 * 数据更新脚本（每周手动跑 1 次）
 * 用途：从 JSON 模板生成新的 data.json
 * 运行：node scripts/fetch-news.js
 *
 * 你的工作流：
 * 1. 打开 G1 PE / NE10 / Recife Alerta 等网站
 * 2. 找 5-15 条本周犯罪新闻（带视频或图片）
 * 3. 填到 INCIDENTS_INPUT 下面的数组
 * 4. 跑 node scripts/fetch-news.js
 * 5. git add . && git commit -m "update data" && git push
 * 6. Vercel 自动重新部署
 */

const fs = require('fs');
const path = require('path');

// ====== 在这里填入本周收集的新闻 ======
const INCIDENTS_INPUT = [
  // 复制下面的模板，每个新闻一条：
  // {
  //   type: 'roubo',  // 'roubo' 或 'furto'
  //   title: 'Roubo a transeunte na Av. ...',
  //   description: '简短描述',
  //   location_name: 'Av. Boa Viagem · Boa Viagem',
  //   lat: -8.1175,
  //   lng: -34.9015,
  //   video_url: 'https://www.youtube.com/embed/VIDEO_ID',
  //   thumbnail_url: 'https://...',  // 留空用占位图
  //   duration_str: '0:32',
  //   author_name: 'G1 PE',
  //   verified: true,
  //   is_pulse: false,  // 是否高亮（重大事件）
  //   source_url: 'https://g1.globo.com/...',
  //   publish_offset_hours: 3,  // 几小时前发布
  // },
];

// ====== 自动生成函数 ======
function buildIncident(input, idx){
  const now = new Date();
  const publishTime = new Date(now.getTime() - (input.publish_offset_hours || 0) * 3600 * 1000);
  const id = `rec_${String(idx + 1).padStart(3, '0')}`;
  
  return {
    id,
    type: input.type,
    title: input.title,
    description: input.description || '',
    location_name: input.location_name,
    lat: input.lat,
    lng: input.lng,
    video_url: input.video_url || '',
    thumbnail_url: input.thumbnail_url || `https://picsum.photos/seed/${id}/400/300`,
    duration_str: input.duration_str || '0:30',
    duration_sec: parseDuration(input.duration_str || '0:30'),
    author_name: input.author_name,
    author_avatar_letter: input.author_name.charAt(0).toUpperCase(),
    publish_time_iso: publishTime.toISOString(),
    publish_time_relative: relativeTime(input.publish_offset_hours || 0),
    verified: !!input.verified,
    is_pulse: !!input.is_pulse,
    source_url: input.source_url || ''
  };
}

function parseDuration(str){
  const [m, s] = str.split(':').map(Number);
  return (m || 0) * 60 + (s || 0);
}

function relativeTime(hours){
  if(hours < 1) return 'agora';
  if(hours < 24) return `há ${Math.round(hours)}h`;
  if(hours < 48) return 'ontem';
  return `há ${Math.floor(hours / 24)}d`;
}

// ====== 主流程 ======
function main(){
  if(INCIDENTS_INPUT.length === 0){
    console.warn('⚠️  INCIDENTS_INPUT is empty. Edit scripts/fetch-news.js to add data.');
    console.log('💡 保留现有 data.json 不变');
    return;
  }

  const incidents = INCIDENTS_INPUT.map(buildIncident);

  const output = {
    city: {
      id: 'recife',
      name: 'Recife, PE',
      country: 'BR',
      lat: -8.0476,
      lng: -34.8770,
      timezone: 'America/Recife'
    },
    meta: {
      last_updated: new Date().toISOString(),
      data_source: 'manual',
      total_count: incidents.length,
      period_days: 7
    },
    incidents
  };

  const outPath = path.join(__dirname, '../public/data.json');
  fs.writeFileSync(outPath, JSON.stringify(output, null, 2), 'utf-8');
  console.log(`✅ Written ${incidents.length} incidents to ${outPath}`);
  console.log(`📅 Last updated: ${output.meta.last_updated}`);
}

main();
