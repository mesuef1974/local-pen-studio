export const MAX_APPROVED_PATHS=10_000;

export function isApprovedVector(vector,width,height){
 return !!(vector&&vector.width===width&&vector.height===height&&Array.isArray(vector.paths)&&
  vector.paths.length<=MAX_APPROVED_PATHS&&vector.paths.every(path=>Array.isArray(path)&&path.length>=2&&
   path.every(point=>Array.isArray(point)&&point.length===2&&point.every(Number.isFinite)&&
    point[0]>=0&&point[0]<vector.width&&point[1]>=0&&point[1]<vector.height)));
}
