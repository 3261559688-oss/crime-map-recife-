// 📊 快手 Trinity 埋点抽象层（@kibt/weblogger 适配版）
// 完整代码见 public/index.html 第 488~720 行

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
