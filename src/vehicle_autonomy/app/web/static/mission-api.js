'use strict';
window.VAF = {
  catalog: [], target: '',
  async call(path, payload) {
    const token = document.querySelector('#token').value.trim();
    const headers = {'Authorization': 'Bearer ' + token};
    const options = {headers};
    if (payload !== undefined) {
      Object.assign(headers, {'Content-Type':'application/json', 'X-VAF-CSRF':token, 'X-VAF-Request-ID':crypto.randomUUID()});
      Object.assign(options, {method:'POST', body:JSON.stringify(payload)});
    }
    const response = await fetch(path, options);
    const data = await response.json();
    if (!response.ok || !data.ok) throw Error(data.error || 'Request failed');
    return data.result;
  },
  node(tag, text, attrs={}) {
    const e = document.createElement(tag); if (text !== undefined) e.textContent = text;
    for (const [k,v] of Object.entries(attrs)) e.setAttribute(k,v); return e;
  },
  report(error) { document.querySelector('#notice').textContent = String(error.message || error); },
  async connect() {
    const vehicles = await this.call('/api/vehicles');
    const select = document.querySelector('#target'); select.replaceChildren();
    for (const v of vehicles) select.append(this.node('option', `${v.target} · ${v.kind}`, {value:v.target}));
    if (!vehicles.length) throw Error('No owned simulation vehicles. Start with explicit --simulation manifests.');
    this.target = select.value;
    await this.loadCatalog(); return vehicles;
  },
  async loadCatalog() { this.target=document.querySelector('#target').value; this.catalog=await this.call('/api/actions?target='+encodeURIComponent(this.target)); },
  parameters(container, schema, values, onChange) {
    container.replaceChildren();
    for (const [name, property] of Object.entries(schema.properties || {})) {
      const label=this.node('label', name); let input;
      if (values[name] && typeof values[name]==='object' && values[name].$query) {
        input=this.node('input');input.value=JSON.stringify(values[name]);input.readOnly=true;
        input.title='Typed observation binding; edit in Mission JSON';label.append(input);container.append(label);continue;
      }
      if (property.enum) {
        input=this.node('select'); for (const v of property.enum) input.append(this.node('option',String(v),{value:JSON.stringify(v)}));
        input.value=JSON.stringify(values[name] ?? property.default ?? property.enum[0]);
      } else {
        input=this.node('input'); input.type=property.type==='boolean'?'checkbox':property.type==='string'?'text':'number';
        if(input.type==='checkbox') input.checked=values[name] ?? property.default ?? false;
        else input.value=values[name] ?? property.default ?? property.const ?? '';
        if(property.minimum!==undefined) input.min=property.minimum;
        if(property.maximum!==undefined) input.max=property.maximum;
        if(input.type==='number') input.step=property.type==='integer'?'1':'any';
      }
      input.name=name; input.title=property.description || '';
      if(property.const!==undefined) input.disabled=true;
      const read=()=>property.enum?JSON.parse(input.value):input.type==='checkbox'?input.checked:input.type==='number'?Number(input.value):input.value;
      values[name]=read(); input.addEventListener('change',()=>{ values[name]=read(); if(onChange)onChange(); });
      label.append(input); container.append(label);
    }
  },
  guard(fn) { return async (...args)=>{try {document.querySelector('#notice').textContent=''; return await fn(...args);}catch(e){this.report(e);}}; }
};
