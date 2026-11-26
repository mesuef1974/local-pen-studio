// Stage freshness and approval are separate: viewing a result does not approve it.
export class Workflow{
 constructor(){this.stage=0;this.source='';this.original='';this.name='';this.outputs=[null,null,null];this.fresh=[false,false,false];this.approved=[false,false];this.versions=[0,0,0];this.checks=[false,false,false,false];}
 invalidate(from){if(from<2)this.checks=this.checks.map(()=>false);for(let i=from;i<3;i++){this.versions[i]++;this.fresh[i]=false;if(i<2)this.approved[i]=false;}}
 import(image,name){this.original=this.source=image;this.name=name;this.stage=0;this.outputs=[null,null,null];this.invalidate(0);}
 reviewImage(result,reference=this.original||this.source){if(!result?.image||!Number.isInteger(result.width)||!Number.isInteger(result.height)||result.width<1||result.height<1)throw Error('يلزم رسم خطي صالح.');this.invalidate(0);this.source=result.image;if(!this.original)this.original=result.image;this.outputs=[{...result},{...result,direct:true,reference},null];this.fresh=[true,true,false];this.approved=[true,false];this.stage=1;}
 canEnter(stage){return stage===0||(stage===1&&this.fresh[0]&&this.approved[0])||(stage===2&&this.fresh[0]&&this.approved[0]&&this.fresh[1]&&this.approved[1]);}
 publish(stage,version,data){if(version!==this.versions[stage]||!this.canEnter(stage))return false;this.outputs[stage]=data;this.fresh[stage]=true;return true;}
 approve(stage){if(stage>1||!this.fresh[stage]||!this.canEnter(stage))return false;this.approved[stage]=true;return true;}
 navigate(stage){if(!this.canEnter(stage))return false;this.stage=stage;return true;}
}
