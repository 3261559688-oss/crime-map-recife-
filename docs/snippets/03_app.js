<script>
/* ============================================================
   📊 埋点抽象层 - Trinity 适配版（快手站内规范）
   设计：所有业务代码只调 track(event, props)
   接入 Kwai App: 自动走 window.__radar.track（native bridge）
   接入 Kwai Web: 自动走 window.kuaishouLog.report
   浏览器调试: 走 console（__CM_DEBUG=true）
   ============================================================ */
(function(){
  // ---- 匿名 UID / SID ----
  let uid=localStorage.getItem('cm_uid');
  if(!uid){uid='u_'+Date.now().toString(36)+Math.random().toString(36).slice(2,8);localStorage.setItem('cm_uid',uid);}
  let sid=sessionStorage.getItem('cm_sid');
  if(!sid){sid='s_'+Date.now().toString(36)+Math.random().toString(36).slice(2,6);sessionStorage.setItem('cm_sid',sid);}
  window.__CM_UID=uid;window.__CM_SID=sid;

  // ---- 设备/环境 ----
  const ua=navigator.userAgent;
  const isMobile=/Mobi|Android|iPhone|iPad/i.test(ua);
  const ctx={
    uid,sid,page:location.pathname,referrer:document.referrer||'',
    ua,is_mobile:isMobile,
    screen_w:screen.width,screen_h:screen.height,
    lang:navigator.language,tz:Intl.DateTimeFormat().resolvedOptions().timeZone,
  };
  window.__CM_CTX=ctx;

  // ---- 页面动作计数器（用于 TASK_EVENT 上报）----
  const counters={
    city_switch_count:0, type_switch_count:0,
    marker_click_count:0, list_click_count:0,
    news_open_count:0, max_scroll_pct:0,
  };
  window.__CM_COUNTERS=counters;

  // ---- 活跃时长统计（仅前台累计）----
  let activeMs=0, lastTick=Date.now();
  setInterval(()=>{
    if(document.visibilityState==='visible'){activeMs+=Date.now()-lastTick;}
    lastTick=Date.now();
  },5000);
  window.__CM_GET_ACTIVE_MS=()=>activeMs;

  // ============================================================
  // 🎯 Trinity 协议映射表
  //   event -> { type, el, page, area }
  //     type:  PAGE_SHOW_EVENT / ELEMENT_SHOW_EVENT / CLICK_EVENT / TASK_EVENT
  //     el:    element_package.action2 (英文大写下划线)
  //     area:  click_area 简写（部分 CITY_SWITCH_POPUP 用）
  // ============================================================
  const PAGE_NAME='CRIME_MAP_PAGE';
  const TRINITY_MAP={
    // 页面曝光
    page_view:           {type:'PAGE_SHOW_EVENT'},
    // 元素曝光
    city_button_show:    {type:'ELEMENT_SHOW_EVENT', el:'CITY_SWITCH_BUTTON'},
    type_filter_show:    {type:'ELEMENT_SHOW_EVENT', el:'CRIME_TYPE_FILTER'},
    marker_exposure:     {type:'ELEMENT_SHOW_EVENT', el:'CRIME_MARKER'},
    list_item_exposure:  {type:'ELEMENT_SHOW_EVENT', el:'CRIME_LIST_ITEM'},
    city_modal_open:     {type:'ELEMENT_SHOW_EVENT', el:'CITY_SWITCH_POPUP'},
    // 点击事件
    city_switch:         {type:'CLICK_EVENT', el:'CITY_SWITCH_BUTTON'},
    city_picked:         {type:'CLICK_EVENT', el:'CITY_SWITCH_POPUP', area:'city_list'},
    city_search:         {type:'CLICK_EVENT', el:'CITY_SWITCH_POPUP', area:'search_box'},
    city_modal_cancel:   {type:'CLICK_EVENT', el:'CITY_SWITCH_POPUP', area:'cancel'},
    type_filter:         {type:'CLICK_EVENT', el:'CRIME_TYPE_FILTER'},
    marker_click:        {type:'CLICK_EVENT', el:'CRIME_MARKER'},
    list_item_click:     {type:'CLICK_EVENT', el:'CRIME_LIST_ITEM'},
    news_open:           {type:'CLICK_EVENT', el:'NEWS_OUTLINK'},
    sheet_toggle:        {type:'CLICK_EVENT', el:'LIST_SHEET_HANDLE'},
    // 任务事件
    session_end:         {type:'TASK_EVENT', task:'PAGE_DURATION'},
    // 异常
    error:               {type:'CLICK_EVENT', el:'PAGE_ERROR'},
  };

  // ---- 缓冲队列 ----
  const queue=[];
  let flushTimer=null;
  function flush(){
    if(!queue.length)return;
    const batch=queue.splice(0,queue.length);
    sendToBackend(batch);
  }
  function scheduleFlush(){
    if(flushTimer)return;
    flushTimer=setTimeout(()=>{flushTimer=null;flush();},2000);
  }

  // 🔥 上报通道（按 @kibt/weblogger 官方规范）
  //   生产: window.kwailog.sendPv/sendClick/sendShow（项目里 import @kibt/weblogger 后挂全局）
  //   降级: 直接 POST https://logsdk.kwai-pro.com/rest/wd/common/log/collect/misc2
  //   调试: console
  const RADAR_HTTP_ENDPOINT='https://logsdk.kwai-pro.com/rest/wd/common/log/collect/misc2';
  const RADAR_PROJECT_ID='04dd286660';

  // 读 cookie 工具
  function _ck(k){
    const m=document.cookie.match(new RegExp('(?:^|; )'+k+'=([^;]*)'));
    return m?decodeURIComponent(m[1]):'';
  }
  function _qs(k){
    return new URLSearchParams(location.search).get(k)||'';
  }
  // 平台标识：H5=4（按 weblogger getPlatform 默认值；接入站内时由 SDK 重写）
  function _platform(){
    const ua=navigator.userAgent;
    if(/Android/i.test(ua))return 1;
    if(/iPhone|iPad|iOS/i.test(ua))return 2;
    return 4; // H5
  }

  // 构建官方基础参数（每条都带）
  function buildBaseParams(){
    return {
      product_name: _ck('kpn') || _qs('kpn') || 'KWAI',
      package_name: _ck('kpn') || _qs('kpn') || 'KWAI',
      platform: _platform(),
      version_name: _ck('appver') || '',
      user_id: _ck('ud') || uid,
      network_type: _ck('net') || '',
      h5_extra_attr: {
        country_name: {
          country: _ck('countryInfo') || _qs('country') || 'BR',
          bucket: _ck('bucket') || ''
        },
        channel: _qs('source') || 'CRIME_MAP_BANNER'
      }
    };
  }

  function sendToBackend(events){
    events.forEach(e=>{
      const cfg=TRINITY_MAP[e.event];
      if(!cfg)return;
      const props=e.props||{};
      if(cfg.area)props.click_area=cfg.area;

      // 🅰️ Kwai App 内 / 已接入 @kibt/weblogger（生产）
      const kw=window.kwailog;
      if(kw && typeof kw.sendPv==='function'){
        try{
          if(cfg.type==='PAGE_SHOW_EVENT'){
            kw.sendPv({page:PAGE_NAME, type:'enter', params:props});
          }else if(cfg.type==='ELEMENT_SHOW_EVENT'){
            kw.sendShow({action:cfg.el, params:props});
          }else if(cfg.type==='CLICK_EVENT'){
            kw.sendClick({action:cfg.el, params:props});
          }else if(cfg.type==='TASK_EVENT'){
            kw.sendClick({action:cfg.task||'PAGE_TASK', type:'STAY_LENGTH_STAT_EVENT', params:props});
          }
        }catch(_){ }
        return;
      }

      // 🅱️ HTTP 直传（端外 / 没引 SDK 时）
      if(window.__CM_HTTP_FALLBACK){
        const body={
          event_type: cfg.type,
          page: PAGE_NAME,
          action: cfg.el || cfg.task || '',
          params: props,
          base_params: buildBaseParams(),
          radar_project: RADAR_PROJECT_ID,
          ts: e.ts
        };
        try{
          const blob=new Blob([JSON.stringify(body)],{type:'application/json'});
          if(navigator.sendBeacon)navigator.sendBeacon(RADAR_HTTP_ENDPOINT, blob);
          else fetch(RADAR_HTTP_ENDPOINT,{method:'POST',keepalive:true,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).catch(()=>{});
        }catch(_){ }
        return;
      }

      // 🅲 浏览器调试
      if(window.__CM_DEBUG){
        const action=cfg.el||cfg.task||PAGE_NAME;
        console.log('%c📊 Trinity %c '+cfg.type+' %c '+action,
          'background:#dc2626;color:#fff;padding:2px 6px;border-radius:3px',
          'background:#1e40af;color:#fff;padding:2px 6px',
          'color:#666',
          {event:e.event, props, base:buildBaseParams()});
      }
    });
  }

  // ---- 公开 API ----
  window.track=function(event,props){
    queue.push({event, props:props||{}, ts:Date.now(), uid, sid, url:location.href});
    scheduleFlush();
  };

  // ---- 曝光观察器（IntersectionObserver）----
  const exposeOb=new IntersectionObserver((entries)=>{
    entries.forEach(en=>{
      if(en.isIntersecting && en.intersectionRatio>=0.5){
        const el=en.target;
        if(el.__exposed)return;
        // 进入视口 500ms 才算
        el.__expTimer=setTimeout(()=>{
          if(el.__exposed)return;
          el.__exposed=true;
          const event=el.dataset.expEvent;
          const data=el.__expData||{};
          if(event)track(event, data);
          exposeOb.unobserve(el);
        },500);
      }else{
        if(en.target.__expTimer){clearTimeout(en.target.__expTimer);en.target.__expTimer=null;}
      }
    });
  },{threshold:[0.5]});
  window.__CM_EXPOSE=function(el, event, data){
    if(!el || el.__expRegistered)return;
    el.__expRegistered=true;
    el.dataset.expEvent=event;
    el.__expData=data;
    exposeOb.observe(el);
  };

  // ---- 页面关闭强制 flush ----
  window.addEventListener('pagehide',flush);
  window.addEventListener('beforeunload',flush);

  // 默认开调试（接入站内时可关）
  window.__CM_DEBUG=true;
})();

const TYPE_EMOJI={homicidio:'🩸',roubo:'🔫',furto:'📱',estupro:'⚠️',trafico:'💊',sequestro:'🔗',violencia:'👊',policia:'👮',faccao:'🔥',fraude:'💳',veiculo:'🚗',menor:'👦',outros:'❗'};
const TYPE_LABEL={homicidio:'Homicídio',roubo:'Roubo',furto:'Furto',estupro:'Estupro',trafico:'Tráfico',sequestro:'Sequestro',violencia:'Violência',policia:'Polícia',faccao:'Facção',fraude:'Fraude',veiculo:'Veículo',menor:'Menor',outros:'Outros'};
const TYPE_COLOR={homicidio:'#7f1d1d',roubo:'#dc2626',furto:'#d97706',estupro:'#be185d',trafico:'#7e22ce',sequestro:'#0891b2',violencia:'#ea580c',policia:'#1e40af',faccao:'#831843',fraude:'#0d9488',veiculo:'#374151',menor:'#a16207',outros:'#475569'};

const CITY_COORDS={
  'Brasil':[-14.235,-51.925,4],
  'São Paulo':[-23.5505,-46.6333,11],
  'Rio de Janeiro':[-22.9068,-43.1729,11],
  'Recife':[-8.0476,-34.8770,12],
  'Salvador':[-12.9714,-38.5014,11],
  'Brasília':[-15.7975,-47.8919,11],
  'Fortaleza':[-3.7172,-38.5433,11],
  'Belo Horizonte':[-19.9167,-43.9345,11],
  'Porto Alegre':[-30.0346,-51.2177,11],
  'Curitiba':[-25.4284,-49.2733,11],
  'Caruaru':[-8.2842,-35.9760,12],
  'Osasco':[-23.5325,-46.7919,12],
  'São Gonçalo':[-22.8268,-43.0537,12],
  'Niterói':[-22.8833,-43.1036,12],
  'Porto Seguro':[-16.4497,-39.0647,12],
};

let allData=[],map,markers=[],curCity='Brasil',curType='all';

// 时钟
function updateClock(){
  const d=new Date();
  document.getElementById('clock').textContent=
    d.getHours().toString().padStart(2,'0')+':'+d.getMinutes().toString().padStart(2,'0');
}
updateClock();setInterval(updateClock,30000);

function showToast(msg,t=1500){
  const el=document.getElementById('toast');
  el.textContent=msg;el.classList.add('show');
  setTimeout(()=>el.classList.remove('show'),t);
}
function escapeHtml(s){return String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}

// 时间格式化：返回 "há 2 horas" / "há 3 dias"
function timeAgo(isoStr){
  if(!isoStr) return {text:'', cls:''};
  const t = new Date(isoStr).getTime();
  if(isNaN(t)) return {text:'', cls:''};
  const sec = Math.floor((Date.now()-t)/1000);
  if(sec < 60) return {text:'agora', cls:'hot'};
  if(sec < 3600) return {text:`há ${Math.floor(sec/60)}min`, cls:'hot'};
  if(sec < 86400){const h=Math.floor(sec/3600);return {text:`há ${h}h`, cls:h<6?'hot':'fresh'}}
  const d = Math.floor(sec/86400);
  if(d===1) return {text:'ontem', cls:'fresh'};
  if(d<7) return {text:`há ${d} dias`, cls:''};
  return {text:`há ${d}d`, cls:''};
}

function initMap(){
  map=L.map('map',{zoomControl:false,attributionControl:true}).setView([-14.235,-51.925],4);
  tileLayer = L.tileLayer(getTileUrl(),{maxZoom:19,subdomains:'abcd'}).addTo(map);
  setTimeout(()=>map.invalidateSize(),200);
  window.addEventListener('resize',()=>map.invalidateSize());
}

// ========== 主题切换 ==========
let tileLayer=null;
function getTileUrl(){
  const theme=document.documentElement.getAttribute('data-theme')||'dark';
  const style=theme==='light'?'light_all':'dark_all';
  return `https://{s}.basemaps.cartocdn.com/${style}/{z}/{x}/{y}{r}.png`;
}
// 固定浅色主题
document.documentElement.setAttribute('data-theme','light');

// 城市统计
function getCityStats(){
  const counts={};
  allData.forEach(d=>{counts[d.city]=(counts[d.city]||0)+1});
  return counts;
}

// 渲染城市选择列表
function renderCityList(filter=''){
  const counts=getCityStats();
  const cities=Object.entries(counts).sort((a,b)=>b[1]-a[1]);
  
  const list=[];
  // 巴西全国置顶
  if(!filter || 'brasil'.includes(filter.toLowerCase())){
    list.push({name:'Brasil',count:allData.length,isAll:true});
  }
  cities.forEach(([city,n])=>{
    if(!filter || city.toLowerCase().includes(filter.toLowerCase())){
      const sample=allData.find(d=>d.city===city);
      list.push({name:city,count:n,state:sample?.state||''});
    }
  });
  
  const el=document.getElementById('cityList');
  if(list.length===0){
    el.innerHTML='<div class="city-opt-empty">Nenhuma cidade encontrada</div>';
    return;
  }
  el.innerHTML=list.map(c=>`
    <div class="city-opt ${curCity===c.name?'active':''}" data-city="${escapeHtml(c.name)}">
      <div class="city-opt-left">
        <span>${c.isAll?'🇧🇷':'📍'}</span>
        <div>
          <div class="city-opt-name">${escapeHtml(c.name)}</div>
          ${c.state?`<div class="city-opt-state">${escapeHtml(c.state)}</div>`:''}
        </div>
      </div>
      <div class="city-opt-count">${c.count}</div>
    </div>
  `).join('');
  
  el.querySelectorAll('.city-opt').forEach(opt=>{
    opt.onclick=()=>{
      switchCity(opt.dataset.city);
      closeCityModal();
    };
  });
}

function openCityModal(){
  document.getElementById('cityModal').classList.add('show');
  document.getElementById('citySearch').value='';
  renderCityList();
}
function closeCityModal(){
  document.getElementById('cityModal').classList.remove('show');
}

// 类型筛选
function renderTypeBar(){
  const filtered=curCity==='Brasil'?allData:allData.filter(d=>d.city===curCity);
  const counts={};
  filtered.forEach(d=>{counts[d.type]=(counts[d.type]||0)+1});
  
  const bar=document.getElementById('typeBar');
  let html=`<div class="type-chip ${curType==='all'?'active':''}" data-type="all">Todos · ${filtered.length}</div>`;
  Object.entries(counts).sort((a,b)=>b[1]-a[1]).forEach(([t,n])=>{
    html+=`<div class="type-chip ${curType===t?'active':''}" data-type="${t}">${TYPE_EMOJI[t]||'❗'} ${TYPE_LABEL[t]||t} · ${n}</div>`;
  });
  bar.innerHTML=html;
  
  bar.querySelectorAll('.type-chip').forEach(el=>{
    el.onclick=()=>switchType(el.dataset.type);
  });
}

function switchCity(city){
  const from=curCity;
  curCity=city;
  curType='all';
  document.getElementById('cityBtnLabel').textContent=city;
  const [lat,lng,zoom]=CITY_COORDS[city]||[-14.235,-51.925,4];
  map.flyTo([lat,lng],zoom,{duration:.8});
  renderTypeBar();
  renderMarkers();
  renderList();
  showToast(`📍 ${city}`);
  __CM_COUNTERS.city_switch_count++;
  track('city_switch',{from_city:from,city_name:city,result_count:getFilteredData().length});
}

function switchType(t){
  const from=curType;
  curType=t;
  renderTypeBar();
  renderMarkers();
  renderList();
  __CM_COUNTERS.type_switch_count++;
  track('type_filter',{from_type:from,crime_type:t,city_name:curCity,result_count:getFilteredData().length});
}

function getFilteredData(){
  let d=allData;
  if(curCity!=='Brasil')d=d.filter(x=>x.city===curCity);
  if(curType!=='all')d=d.filter(x=>x.type===curType);
  return d;
}

function renderMarkers(){
  markers.forEach(m=>map.removeLayer(m));
  markers=[];
  const data=getFilteredData();
  data.forEach((d,idx)=>{
    const icon=L.divIcon({className:'',html:`<div class="pm ${d.type}">${TYPE_EMOJI[d.type]||'❗'}</div>`,iconSize:[32,32],iconAnchor:[16,16]});
    const m=L.marker([d.lat,d.lng],{icon}).addTo(map);
    const html=`
      <span class="pop-type" style="background:${TYPE_COLOR[d.type]}">${TYPE_LABEL[d.type]||d.type}</span>
      <div class="pop-title">${escapeHtml(d.title)}</div>
      <div class="pop-meta">📍 ${escapeHtml(d.city)} · ${escapeHtml(d.source||'')}${d.pub_date?' · '+timeAgo(d.pub_date).text:''}</div>
      <a class="pop-link" href="${escapeHtml(d.link)}" target="_blank" rel="noopener" data-news-id="${escapeHtml(d.id||'')}" data-crime-type="${escapeHtml(d.type||'')}" data-source="${escapeHtml(d.source||'')}">Ler notícia →</a>
    `;
    m.bindPopup(html,{maxWidth:260,minWidth:220,offset:[0,-8]});
    m.on('click',()=>{
      highlightItem(idx);
      __CM_COUNTERS.marker_click_count++;
      track('marker_click',{news_id:d.id||'',crime_type:d.type,city_name:d.city,source:d.source||''});
    });
    markers.push(m);
  });
}

function renderList(){
  const data=getFilteredData();
  document.getElementById('sheetCount').textContent=`${data.length} ocorrências`;
  document.getElementById('sheetTitle').textContent=curCity==='Brasil'?'🇧🇷 Brasil':'📍 '+curCity;
  
  const list=document.getElementById('list');
  if(data.length===0){list.innerHTML='<div class="empty">Nenhuma ocorrência</div>';return}
  
  list.innerHTML=data.map((d,idx)=>`
    <div class="it" data-idx="${idx}">
      <div class="it-row">
        <span class="it-emoji">${TYPE_EMOJI[d.type]||'❗'}</span>
        <span class="it-tag" style="background:${TYPE_COLOR[d.type]}">${TYPE_LABEL[d.type]||d.type}</span>
        <span class="it-city">${escapeHtml(d.city)}</span>
      </div>
      <div class="it-title">${escapeHtml(d.title)}</div>
      <div class="it-source"><span>${escapeHtml(d.source||'')}</span>${(()=>{const t=timeAgo(d.pub_date);return t.text?`<span class="it-time ${t.cls}">${t.text}</span>`:''})()}</div>
    </div>
  `).join('');
  
  list.querySelectorAll('.it').forEach(el=>{
    const idx=+el.dataset.idx;
    const d=data[idx];
    // 📊 列表项曝光
    if(window.__CM_EXPOSE){
      window.__CM_EXPOSE(el,'list_item_exposure',{news_id:d.id||'',crime_type:d.type,city_name:d.city,position:idx});
    }
    el.onclick=()=>{
      const idx=+el.dataset.idx;
      const d=data[idx];
      map.flyTo([d.lat,d.lng],14,{duration:.6});
      const m=markers[idx];
      setTimeout(()=>m&&m.openPopup(),650);
      highlightItem(idx);
      __CM_COUNTERS.list_click_count++;
      track('list_item_click',{news_id:d.id||'',crime_type:d.type,city_name:d.city,position:idx,source:d.source||''});
    };
  });
}

function highlightItem(idx){
  document.querySelectorAll('.it').forEach(el=>el.classList.remove('active'));
  const el=document.querySelector(`.it[data-idx="${idx}"]`);
  if(el){
    el.classList.add('active');
    el.scrollIntoView({behavior:'smooth',block:'center'});
  }
  expandSheet();
}

// ========== Sheet 拖拽实现 ==========
const sheet=document.getElementById('sheet');
const sheetHandle=document.getElementById('sheetHandle');

let sheetH=0; // sheet 高度
let curOffset=0; // 当前 transform 偏移（0=完全展开，sheetH-56=收起）
let dragStartY=0;
let dragStartOffset=0;
let isDragging=false;

function getSheetH(){return sheet.offsetHeight}

function setOffset(offset, animated=false){
  const max=getSheetH()-56; // 56 = handle + header 露出高度
  offset=Math.max(0,Math.min(max,offset));
  curOffset=offset;
  if(animated)sheet.classList.remove('no-trans');
  else sheet.classList.add('no-trans');
  sheet.style.transform=`translateY(${offset}px)`;
}

function expandSheet(){setOffset(0,true)}
function collapseSheet(){setOffset(getSheetH()-56,true)}
function isCollapsed(){return curOffset>(getSheetH()-56)*0.5}

// 初始位置：收起
window.addEventListener('load',()=>{
  setTimeout(()=>{
    setOffset(getSheetH()-56,false);
  },50);
});

function onDragStart(e){
  isDragging=true;
  dragStartY=e.touches?e.touches[0].clientY:e.clientY;
  dragStartOffset=curOffset;
  sheet.classList.add('dragging','no-trans');
  e.preventDefault();
}
function onDragMove(e){
  if(!isDragging)return;
  const y=e.touches?e.touches[0].clientY:e.clientY;
  const dy=y-dragStartY;
  setOffset(dragStartOffset+dy,false);
  e.preventDefault();
}
function onDragEnd(){
  if(!isDragging)return;
  isDragging=false;
  sheet.classList.remove('dragging');
  // 自动吸附：根据当前位置吸附到最近的端点
  const max=getSheetH()-56;
  if(curOffset<max*0.4){
    expandSheet();
  }else{
    collapseSheet();
  }
}

sheetHandle.addEventListener('touchstart',onDragStart,{passive:false});
sheetHandle.addEventListener('touchmove',onDragMove,{passive:false});
sheetHandle.addEventListener('touchend',onDragEnd);
sheetHandle.addEventListener('mousedown',onDragStart);
window.addEventListener('mousemove',onDragMove);
window.addEventListener('mouseup',onDragEnd);

// 点击 handle 也能切换
sheetHandle.addEventListener('click',e=>{
  if(Math.abs(e.clientY-dragStartY)<3){ // 没移动太多 = 点击
    const _from=isCollapsed()?'collapsed':(sheet.classList.contains('expanded')?'expanded':'collapsed');
    if(isCollapsed()){expandSheet();track('sheet_toggle',{action:'expand',from_state:_from});}
    else{collapseSheet();track('sheet_toggle',{action:'collapse',from_state:_from});}
  }
});

// ========== 城市按钮 ==========
document.getElementById('cityBtn').addEventListener('click',()=>{openCityModal();track('city_modal_open',{from_city:curCity});});
document.getElementById('cityClose').addEventListener('click',closeCityModal);
document.getElementById('cityModal').addEventListener('click',e=>{
  if(e.target.id==='cityModal')closeCityModal();
});
document.getElementById('citySearch').addEventListener('input',e=>{
  renderCityList(e.target.value);
  if(e.target.value.length>=2)track('city_search',{q:e.target.value,match_count:0});
});
document.getElementById('cityClose').addEventListener('click',()=>{track('city_modal_cancel',{from_city:curCity});});

// ========== 启动 ==========
// 跟随用户首次「读新闻」按钮拦截：通过事件委托（popup 是动态创建的）
document.addEventListener('click',function(e){
  const a=e.target.closest('.pop-link');
  if(a){
    __CM_COUNTERS.news_open_count++;
    let _domain='';try{_domain=new URL(a.href).hostname;}catch(_){}
    const _from=a.closest('.list-item')?'list_item':'marker_popup';
    track('news_open',{news_id:a.dataset.newsId||'',crime_type:a.dataset.crimeType||curType,target_domain:_domain,source:a.dataset.source||'',from_element:_from});
  }
});

async function init(){
  try{
    initMap();
    const t0=performance.now();
    const res=await fetch('/rss_incidents.json?_='+Date.now());
    allData=await res.json();
    renderTypeBar();
    renderMarkers();
    renderList();
    document.getElementById('loading').style.display='none';
    setTimeout(()=>map.invalidateSize(),300);

    // 📊 页面访问主事件
    track('page_view',{
      total_count:allData.length,
      load_ms:Math.round(performance.now()-t0),
      default_city:curCity,
      is_first_visit:!localStorage.getItem('cm_visited')?'TRUE':'FALSE',
      ...window.__CM_CTX,
    });
    localStorage.setItem('cm_visited','1');

    // 📊 元素曝光埋点
    if(window.__CM_EXPOSE){
      window.__CM_EXPOSE(document.getElementById('cityBtn'),'city_button_show',{city_name:curCity});
      window.__CM_EXPOSE(document.querySelector('.type-bar')||document.body,'type_filter_show',{current_type:curType,type_count:14});
    }

    // 📊 停留时长上报（页面关闭时）
    const startedAt=Date.now();
    let maxScroll=0;
    document.querySelector('.list')?.addEventListener('scroll',e=>{
      const el=e.target;
      const pct=Math.round(el.scrollTop/(el.scrollHeight-el.clientHeight)*100);
      if(pct>maxScroll)maxScroll=pct;
    });
    let _exitType='close';
    document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden')_exitType='switch_tab';});
    window.addEventListener('popstate',()=>{_exitType='back';});
    function _reportSessionEnd(){
      __CM_COUNTERS.max_scroll_pct=maxScroll;
      track('session_end',{
        duration_ms:Date.now()-startedAt,
        active_ms:window.__CM_GET_ACTIVE_MS(),
        ...__CM_COUNTERS,
        last_city:curCity,
        last_type:curType,
        exit_type:_exitType,
      });
    }
    window.addEventListener('pagehide',_reportSessionEnd);
  }catch(e){
    document.getElementById('loading').innerHTML=`<div style="color:#ef4444">Erro: ${e.message}</div>`;
    track('error',{message:String(e.message||e),stack:String(e.stack||'').slice(0,500)});
  }
}
init();
</script>
