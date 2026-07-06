from __future__ import annotations

_ADMIN_TABLES_JS = """const __page={keys:1,accounts:1};
const __pageSize={keys:10,accounts:10};
function _slicePage(arr,which){
  const size=__pageSize[which];
  const total=Math.max(1,Math.ceil(arr.length/size));
  if(__page[which]>total)__page[which]=total;
  if(__page[which]<1)__page[which]=1;
  const start=(__page[which]-1)*size;
  return {items:arr.slice(start,start+size),page:__page[which],total:total,count:arr.length};
}
function _setPage(which,p){__page[which]=p;which==='keys'?loadKeys():loadAccounts()}
function _setPageSize(which,s){__pageSize[which]=parseInt(s,10)||10;__page[which]=1;which==='keys'?loadKeys():loadAccounts()}
function _pageFoot(which,pg){
  const sizes=[10,20,50,100];
  let opts='';sizes.forEach(s=>{opts+='<option value="'+s+'"'+(s===__pageSize[which]?' selected':'')+'>'+s+'</option>'});
  const info=t('page_info').replace('{cur}',pg.page).replace('{total}',pg.total).replace('{count}',pg.count);
  return '<div class="tbl-foot"><div class="page-size"><span>'+t('page_size_label')+'</span><select class="page-select" onchange="_setPageSize(\\''+which+'\\',this.value)">'+opts+'</select><span>'+t('page_size_unit')+'</span></div>'
    +'<div class="page-nav"><button class="page-btn" '+(pg.page<=1?'disabled':'')+' onclick="_setPage(\\''+which+'\\','+(pg.page-1)+')">'+t('page_prev')+'</button>'
    +'<span class="page-info">'+info+'</span>'
    +'<button class="page-btn" '+(pg.page>=pg.total?'disabled':'')+' onclick="_setPage(\\''+which+'\\','+(pg.page+1)+')">'+t('page_next')+'</button></div></div>';
}"""
