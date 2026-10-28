import {dispatch} from './engine.mjs';
export function respond(request) {
  try{return {ok:true,result:dispatch(request)};}
  catch(error){return {ok:false,error:{code:error.code||'input',message:error.message,details:error.details||{}}};}
}
