// The single busy coordinator: what is running, and what waits for it to finish.
export function createWorkGate({load,runStage,canRun,isAuto}){
 const gate={busy:false,editorActive:false,queuedFile:null,pendingStage:null,timer:0,
  // A file that arrived during other work is imported first; it makes a queued stage run obsolete.
  drainFile(){const file=gate.queuedFile;if(!file)return false;gate.queuedFile=null;load(file);return true;},
  drain(){if(gate.drainFile())return;const next=gate.pendingStage;if(next===null)return;gate.pendingStage=null;if(isAuto(next)&&canRun(next))runStage(next);}};
 return gate;
}
