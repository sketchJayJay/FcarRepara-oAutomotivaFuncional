'use strict';
(() => {
  const form = document.getElementById('order-form');
  if (!form) return;
  const container = document.getElementById('order-items');
  const initial = JSON.parse(document.getElementById('initial-order-items').textContent);
  const money = new Intl.NumberFormat('pt-BR', {style:'currency',currency:'BRL'});
  const number = value => Number.isFinite(Number(value)) ? Number(value) : 0;
  let dirty = false, submitting = false;
  const saveButton = document.getElementById('save-order');
  const saveMarkup = saveButton.innerHTML;

  function totals() {
    let parts = 0, labor = number(form.elements.labor.value);
    [...container.children].forEach(row => {
      const total = number(row.querySelector('[data-key="qty"]').value) * number(row.querySelector('[data-key="price"]').value);
      const isLabor = row.querySelector('[data-key="is_labor"]').value === '1';
      if (isLabor) labor += total; else parts += total;
      row.querySelector('[data-row-total]').textContent = money.format(total);
    });
    document.getElementById('total-parts').textContent = money.format(parts);
    document.getElementById('total-labor').textContent = money.format(labor);
    document.getElementById('total-order').textContent = money.format(parts+labor);
    document.getElementById('save-total').textContent = money.format(parts+labor);
    const count = container.children.length;
    document.getElementById('items-help').textContent = count ? `${count} ${count===1?'item adicionado':'itens adicionados'}. Confira as quantidades e os valores.` : 'Nenhum item adicionado. Use a busca ou os botões acima.';
  }
  function renumber() {
    [...container.children].forEach((row,index) => {
      row.querySelectorAll('[data-key]').forEach(input => input.name = `item_${input.dataset.key}_${index+1}`);
      row.querySelector('[data-remove]').setAttribute('aria-label', `Remover item ${index+1}`);
    });
    totals();
  }
  function addItem(item={}, focus=true) {
    if (container.children.length>=100) {
      document.getElementById('items-help').textContent='Limite de 100 itens atingido. Remova um item antes de adicionar outro.';
      return;
    }
    const row=document.createElement('div');
    row.className='order-item';
    row.innerHTML='<input type="hidden" data-key="inv"><div class="item-row"><label>Descrição<input class="field" data-key="desc" required maxlength="500" placeholder="Descrição da peça ou serviço"></label><label>Quantidade<input class="field" data-key="qty" type="number" step="0.01" min="0.01" required inputmode="decimal"></label><label>Valor unitário (R$)<input class="field" data-key="price" type="number" step="0.01" min="0" required inputmode="decimal"></label><label>Tipo<select class="field" data-key="is_labor"><option value="0">Peça</option><option value="1">Serviço</option></select></label><button type="button" class="icon-button danger-text" data-remove title="Remover item"><svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/></svg></button></div><div class="item-total"><span data-link-info></span><strong data-row-total></strong></div>';
    row.querySelector('[data-key="inv"]').value=item.inventory_id || '';
    row.querySelector('[data-key="desc"]').value=item.description || '';
    row.querySelector('[data-key="qty"]').value=item.qty ?? 1;
    row.querySelector('[data-key="price"]').value=item.unit_price ?? 0;
    const type=row.querySelector('[data-key="is_labor"]');
    type.value=String(Number(item.is_labor)===1?1:0);
    if (Number(item.catalog_is_labor)===1) type.querySelector('[value="0"]').disabled=true;
    row.querySelector('[data-link-info]').textContent=item.inventory_id ? (type.value==='1'?'Serviço do catálogo · sem baixa de estoque':'Peça vinculada ao estoque') : 'Item avulso';
    row.querySelector('[data-remove]').addEventListener('click',()=>{row.remove();dirty=true;renumber();});
    container.append(row);
    renumber();
    if(focus){dirty=true;row.querySelector('[data-key="desc"]').focus();}
  }
  initial.forEach(item=>addItem(item,false));
  document.getElementById('add-part').addEventListener('click',()=>addItem({is_labor:0}));
  document.getElementById('add-service').addEventListener('click',()=>addItem({is_labor:1}));

  function autocomplete(input, box, endpoint, describe, select) {
    let timer, controller, revision=0;
    function close(){box.hidden=true;input.setAttribute('aria-expanded','false');}
    function message(text){box.replaceChildren();const item=document.createElement('div');item.className='compact-empty';item.style.padding='14px';item.textContent=text;box.append(item);box.hidden=false;input.setAttribute('aria-expanded','true');}
    input.addEventListener('input',()=>{
      clearTimeout(timer);controller?.abort();const current=++revision;
      input.setCustomValidity('');
      const q=input.value.trim();
      if(q.length<2){close();return;}
      timer=setTimeout(async()=>{
        controller=new AbortController();
        try{
          const response=await fetch(`${endpoint}?q=${encodeURIComponent(q)}&limit=20`,{signal:controller.signal});
          if(!response.ok)throw new Error('search');
          const data=await response.json();
          if(current!==revision)return;
          box.replaceChildren();
          if(!data.length){message('Nenhum resultado. Tente outro nome ou código.');return;}
          data.forEach(item=>{
            const button=document.createElement('button');button.type='button';button.setAttribute('role','option');button.tabIndex=-1;
            const [title,detail]=describe(item);const strong=document.createElement('strong');strong.textContent=title;const small=document.createElement('small');small.textContent=detail;button.append(strong,small);
            button.addEventListener('click',()=>{select(item);close();});
            button.addEventListener('keydown',event=>{
              if(event.key==='Escape'){close();input.focus();}
              if(event.key==='ArrowDown'){event.preventDefault();button.nextElementSibling?.focus();}
              if(event.key==='ArrowUp'){event.preventDefault();(button.previousElementSibling || input).focus();}
            });box.append(button);
          });box.hidden=false;input.setAttribute('aria-expanded','true');
        }catch(error){if(error.name!=='AbortError'&&current===revision)message('Não foi possível buscar. Confira a conexão e tente novamente.');}
      },220);
    });
    input.addEventListener('keydown',event=>{
      if(event.key==='Escape')close();
      if(event.key==='ArrowDown'&&!box.hidden){event.preventDefault();box.querySelector('button')?.focus();}
      if(event.key==='Enter'&&!box.hidden){event.preventDefault();box.querySelector('button')?.click();}
      else if(event.key==='Enter'&&input.id==='stock-search')event.preventDefault();
    });
    document.addEventListener('click',event=>{if(!box.contains(event.target)&&event.target!==input)close();});
  }
  const clientInput=document.getElementById('client-search');
  const clientId=document.getElementById('client-id');
  const picker=document.getElementById('vehicle-picker');
  const vehicleId=document.getElementById('vehicle-id');
  const plate=document.getElementById('vehicle-plate');
  const model=document.getElementById('vehicle-model');
  let vehicleRevision=0;
  async function loadVehicles(id){
    if(!picker)return;
    const current=++vehicleRevision;
    picker.replaceChildren(new Option('Informar outro veículo',''));
    document.getElementById('vehicle-picker-label').hidden=true;
    if(!id)return;
    try{
      const response=await fetch(`/api/clients/${encodeURIComponent(id)}/vehicles`);
      if(!response.ok)return;const data=await response.json();if(current!==vehicleRevision)return;
      data.forEach(vehicle=>{const option=new Option([vehicle.plate || 'Sem placa',vehicle.model].filter(Boolean).join(' · '),String(vehicle.id));option.dataset.plate=vehicle.plate || '';option.dataset.model=vehicle.model || '';picker.add(option);});
      picker.value=vehicleId.value;document.getElementById('vehicle-picker-label').hidden=!data.length;
    }catch(error){/* Os campos manuais continuam disponíveis. */}
  }
  if(form.dataset.editing!=='true'){
    clientInput.addEventListener('input',()=>{clientId.value='';document.getElementById('client-help').textContent='Escolha um cliente nos resultados.';document.getElementById('client-help').classList.remove('selected');vehicleId.value='';loadVehicles('');});
    autocomplete(clientInput,document.getElementById('client-results'),'/api/clients_search',client=>[client.name,client.phone || 'Telefone não informado'],client=>{
      clientInput.value=client.name;clientId.value=client.id;vehicleId.value='';plate.value='';model.value='';
      document.getElementById('client-help').textContent='Cliente selecionado';document.getElementById('client-help').classList.add('selected');clientInput.setCustomValidity('');dirty=true;loadVehicles(client.id);
    });loadVehicles(clientId.value);
    picker?.addEventListener('change',()=>{const option=picker.selectedOptions[0];vehicleId.value=picker.value;plate.value=option?.dataset.plate || '';model.value=option?.dataset.model || '';dirty=true;});
  }
  autocomplete(document.getElementById('stock-search'),document.getElementById('stock-results'),'/api/inventory_search',item=>[item.name,`${item.sku?item.sku+' · ':''}${money.format(number(item.price))} · ${item.is_labor?'Serviço':`Estoque: ${item.stock}`}`],item=>{
    addItem({inventory_id:item.id,description:item.name,qty:1,unit_price:item.price,is_labor:item.is_labor,catalog_is_labor:item.is_labor});document.getElementById('stock-search').value='';
  });
  form.addEventListener('input',()=>{dirty=true;totals();});
  form.addEventListener('change',()=>{dirty=true;totals();});
  form.addEventListener('submit',event=>{
    if(submitting){event.preventDefault();return;}
    if(!clientId.value){event.preventDefault();clientInput.setCustomValidity('Selecione um cliente nos resultados da busca.');clientInput.reportValidity();clientInput.focus();return;}
    renumber();submitting=true;saveButton.disabled=true;saveButton.textContent='Salvando…';
  });
  window.addEventListener('beforeunload',event=>{if(dirty&&!submitting){event.preventDefault();event.returnValue='';}});
  window.addEventListener('pageshow',()=>{submitting=false;saveButton.disabled=false;saveButton.innerHTML=saveMarkup;});
  totals();
})();
