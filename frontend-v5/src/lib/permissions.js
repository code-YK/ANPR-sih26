const RANK = { viewer: 1, operator: 2 };

export function isSuperAdmin(user) {
  return user?.role === "super_admin";
}

export function isDepartmentAdmin(user) {
  return user?.role === "department_admin";
}

export function canAdminister(user) {
  return isSuperAdmin(user) || isDepartmentAdmin(user);
}

/** Mirrors the backend's department clearance check (the API enforces it). */
export function canAccessDepartment(user, department, clearance = "viewer") {
  if (!user) return false;
  if (isSuperAdmin(user)) return true;
  if (!department) return false;
  const grant = user.grants?.find((item) => item.department === department);
  return Boolean(grant && RANK[grant.clearance] >= RANK[clearance]);
}

/** PUT /cameras/{id} -- and therefore ANPR, whose intent lives on the camera. */
export function canAdminCamera(user, camera) {
  if (!user || !camera) return false;
  if (isSuperAdmin(user)) return true;
  return isDepartmentAdmin(user) && camera.department === user.home_department;
}

export function canOperateCamera(user, camera) {
  return canAccessDepartment(user, camera?.department, "operator");
}

export function canOperateAnywhere(user) {
  if (isSuperAdmin(user)) return true;
  return (user?.grants || []).some((grant) => RANK[grant.clearance] >= RANK.operator);
}
