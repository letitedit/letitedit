/*@block
{"title":"Kinetic type system","about":"Timed words or measured phrases with bundled fonts, character runs, reveals, pops and protected placement. Positions are frame fractions; size is a fraction of frame height.","duration":4,"params":{"words":[],"phrases":[],"layout":{},"protected":[],"roles":{},"font":{"family":"Inter Tight","weight":800},"offset":0,"blend":"normal","readability":null},"docs":{"blend":"Engine glyph-only composition on a kinetic_type timeline item: normal, difference, exclusion, multiply, screen, overlay and Cairo blend modes. The transparent render alone has no background to blend with. Solid fallback: normal with an outline on a separate word or phrase item; never blend a backdrop or shadow.","words":"[{text,start,end,role,x,y,size,font,fill,base_fill,fade_in,spacing,line_height,align,entry,exit,reveal,stagger,from_scale,from_x,from_y,ease,outline,outline_fill,shadow,runs}] end exclusive; seconds. reveal none, wipe, highlight (horizontal base_fill to fill), crossfade (whole word), letters (graphemes stagger seconds apart), runs (explicit run.start onsets, e.g. syllables). ease linear, out, backOut. runs [{text,font?,fill?,start?}] concatenate to text exactly; a run may colour part of a word. fade_in false keeps a reveal visible. Letter mode applies the scale/slide per grapheme; other modes apply them to the word.","phrases":"[{words:[{text,start,end,role,line?,runs?,...}],end?}]. Compiled from bundled font advances; line is an explicit row index. Roles and word settings carry through; onsets are unchanged. No silent shrinking or wrapping. A phrase replaces the words input.","layout":"{canvas:[1080,1920],safe:[left,top,right,bottom],centres:[y,...],gap:0.008,row_gap:0.012}. First collision-free centre wins; bounds include scale overshoot and travel. No fit raises an error. Canvas aspect must match the render.","protected":"[{box:[left,top,right,bottom],start?,end?}] frame fractions and source word-clock seconds; omitted times apply throughout. Placement avoids each region for the whole overlapping phrase.","roles":"Defaults by role; word values override. Manual words use x/y centre unless align left/right.","font":"Bundled {family,weight}; roles, words and runs may use different bundled fonts.","readability":"edge: Difference fill paired with a separate synchronized edge-layer. edge-layer: transparent fill, thin dark stroke, normal blend. solid: white fill with the same companion edge. No boxes; phrase layout includes the edge footprint. Aided modes keep opaque glyphs without fade or reveal."}}
@*/
M.block('kinetic_type', (stage, p, c) => {
  const entries = p.words.map((word) => {
    const settings = Object.assign({x:0.5,y:0.5,size:0.05,fill:'#ffffff',base_fill:'#747474',fade_in:true,spacing:0,line_height:1.1,align:'center',entry:0.15,exit:0.08,reveal:'none',from_scale:1,from_x:0,from_y:0,ease:'out',outline:0,shadow:'none',font:p.font}, p.roles[word.role] || {}, word);
    const aided = ['edge','edge-layer','solid'].includes(p.readability);
    const edgeLayer = p.readability === 'edge-layer';
    if (aided) Object.assign(settings,{fill:edgeLayer ? 'transparent' : '#ffffff',base_fill:'#ffffff',outline:edgeLayer ? .003 : 0,outline_fill:'#101010',shadow:'none',fade_in:false,exit:0,reveal:'none'});
    const element = M.el('div', {text:String(settings.text), style:{position:'absolute',whiteSpace:'pre',left:`${settings.x*c.w}px`,top:`${settings.y*c.h}px`,fontSize:`${settings.size*c.h}px`,fontFamily:settings.font.family,fontWeight:String(settings.font.weight || 400),letterSpacing:`${settings.spacing}em`,lineHeight:String(settings.line_height),color:c.color(settings.fill),textShadow:settings.shadow,webkitTextStroke:`${settings.outline*c.h}px ${settings.outline_fill || '#000000'}`,transformOrigin:'50% 50%',background:'transparent',padding:'0'}}, stage);
    const runs = settings.runs || [];
    const fragments = [];
    if (runs.length || settings.reveal === 'letters') {
      element.textContent = '';
      const segmenter = typeof Intl !== 'undefined' && Intl.Segmenter ? new Intl.Segmenter(undefined,{granularity:'grapheme'}) : null;
      let ordinal = 0;
      (runs.length ? runs : [{text:settings.text}]).forEach((run) => {
        const characters = settings.reveal === 'letters' ? (segmenter ? Array.from(segmenter.segment(run.text),part=>part.segment) : Array.from(run.text)) : [run.text];
        characters.forEach((text) => {
          const font = run.font || settings.font;
          const child = M.el('span',{text,style:{display:['letters','runs'].includes(settings.reveal) ? 'inline-block' : 'inline',fontFamily:font.family,fontWeight:String(font.weight || 400),color:c.color(aided ? settings.fill : run.fill || settings.fill)}},element);
          fragments.push({element:child,fill:run.fill || settings.fill,start:run.start,ordinal:ordinal++});
        });
      });
    }
    if (settings.layout_bounds && element.offsetWidth !== undefined) {
      let peak = Math.max(1,settings.from_scale);
      if (settings.ease === 'backOut') peak += Math.abs(1-settings.from_scale)*0.101;
      const halfWidth = element.offsetWidth*peak/(2*c.w)+settings.outline*c.h/c.w+Math.abs(settings.from_x)*1.11;
      const halfHeight = element.offsetHeight*peak/(2*c.h)+settings.outline+Math.abs(settings.from_y)*1.11;
      const actual = [settings.x-halfWidth,settings.y-halfHeight,settings.x+halfWidth,settings.y+halfHeight];
      const bounds = settings.layout_bounds;
      if (actual[0] < bounds[0] || actual[1] < bounds[1] || actual[2] > bounds[2] || actual[3] > bounds[3]) {
        throw new Error('kinetic_type browser metrics exceed measured layout for '+settings.text+'; recompile or revise the phrase');
      }
    }
    return {element,settings,fragments};
  });
  return (t) => {
    entries.forEach(({element,settings,fragments}) => {
      const start = Number(settings.start) - p.offset;
      const end = Number(settings.end) - p.offset;
      const progress = settings.entry > 0 ? M.prog(t,start,settings.entry,settings.ease) : (t >= start ? 1 : 0);
      const fade = settings.exit > 0 ? M.prog(t,end-settings.exit,settings.exit,'linear') : (t >= end ? 1 : 0);
      const visible = t >= start && t < end;
      const anchor = settings.align === 'left' ? '0%' : settings.align === 'right' ? '-100%' : '-50%';
      const arrival = settings.fade_in && !['letters','runs'].includes(settings.reveal) ? Math.max(0,Math.min(1,progress)) : 1;
      element.style.opacity = String(visible ? arrival*(1-fade) : 0);
      element.style.transform = ['letters','runs'].includes(settings.reveal) ? `translate(${anchor},-50%)` : `translate(${anchor},-50%) translate(${(1-progress)*settings.from_x*c.w}px,${(1-progress)*settings.from_y*c.h}px) scale(${settings.from_scale+(1-settings.from_scale)*progress})`;
      element.style.clipPath = settings.reveal === 'wipe' ? `inset(0 ${(1-Math.max(0,Math.min(1,progress)))*100}% 0 0)` : 'none';
      if (settings.reveal === 'highlight') {
        const percent = Math.max(0,Math.min(1,progress))*100;
        element.style.color = 'transparent';
        element.style.backgroundImage = `linear-gradient(90deg,${c.color(settings.fill)} ${percent}%,${c.color(settings.base_fill)} ${percent}%)`;
        element.style.backgroundClip = 'text';
        element.style.webkitBackgroundClip = 'text';
      } else if (settings.reveal === 'crossfade') {
        const percent = Math.max(0,Math.min(1,progress))*100;
        element.style.color = `color-mix(in srgb,${c.color(settings.base_fill)} ${100-percent}%,${c.color(settings.fill)} ${percent}%)`;
      }
      fragments.forEach((fragment) => {
        const child = fragment.element;
        const onset = settings.reveal === 'runs' ? Number(fragment.start) - p.offset : start + fragment.ordinal * (settings.stagger === undefined ? 0.018 : settings.stagger);
        const local = settings.entry > 0 ? M.prog(t,onset,settings.entry,settings.ease) : (t >= onset ? 1 : 0);
        const fraction = child.offsetWidth ? (Math.max(0,Math.min(1,progress))*element.offsetWidth-child.offsetLeft)/child.offsetWidth : progress;
        const percent = Math.max(0,Math.min(1,settings.reveal === 'highlight' ? fraction : progress))*100;
        if (['letters','runs'].includes(settings.reveal)) {
          child.style.opacity = String(t < onset || !visible ? 0 : settings.fade_in ? Math.max(0,Math.min(1,local)) : 1);
          child.style.transform = `translate(${(1-local)*settings.from_x*c.w}px,${(1-local)*settings.from_y*c.h}px) scale(${settings.from_scale+(1-settings.from_scale)*local})`;
        } else if (settings.reveal === 'highlight') {
          child.style.color = 'transparent';
          child.style.backgroundImage = `linear-gradient(90deg,${c.color(fragment.fill)} ${percent}%,${c.color(settings.base_fill)} ${percent}%)`;
          child.style.backgroundClip = 'text';
          child.style.webkitBackgroundClip = 'text';
        } else if (settings.reveal === 'crossfade') {
          child.style.color = `color-mix(in srgb,${c.color(settings.base_fill)} ${100-percent}%,${c.color(fragment.fill)} ${percent}%)`;
        }
      });
    });
  };
});
