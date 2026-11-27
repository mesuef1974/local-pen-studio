// One snapshot of the current work, kept in this browser only (IndexedDB), so a reload does not lose it.
const NAME='masar-work',STORE='snapshot',KEY='current';

export function createWorkStore(factory=globalThis.indexedDB){
 let opened=null;
 const open=()=>opened||=new Promise((resolve,reject)=>{const request=factory.open(NAME,1);request.onupgradeneeded=()=>request.result.createObjectStore(STORE);request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);}).catch(error=>{opened=null;throw error;});
 const run=async(mode,action)=>{const db=await open();return new Promise((resolve,reject)=>{const transaction=db.transaction(STORE,mode),request=action(transaction.objectStore(STORE));transaction.oncomplete=()=>resolve(request.result);transaction.onerror=transaction.onabort=()=>reject(transaction.error);});};
 return {load:()=>run('readonly',store=>store.get(KEY)),save:value=>run('readwrite',store=>store.put(value,KEY)),clear:()=>run('readwrite',store=>store.delete(KEY))};
}
