# Rename/Remix vertex groups from Daz 3D model to AutoRig Pro
# --- limitations ---
# - no secondary controllers
# - edit limb option on spine for 4 spine bones to be compatible with UE4 mannequin
# - edit limb options on both legs to have toe fingers
# - add breasts / ears (1 bone)

import ast
import logging
import math
import traceback
from dataclasses import dataclass
from enum import Flag
from types import ModuleType
from typing import Callable, Dict, List, Optional, Set, Union

import bpy
import mathutils
from mathutils import Vector, Euler

bl_info = {
    "name": "Daz2ARP",
    "author": "Boonsak Watanavisit",
    "version": (1, 0),
    "blender": (2, 93, 0),
    "location": "View3D",
    "description": "Rename/Remix vertex groups from Daz 3D model to AutoRig Pro",
    "warning": "",
    "doc_url": "",
    "category": "Object",
}


def _try_import_module(name: str, package: Optional[str] = None) -> Optional[ModuleType]:
    import importlib
    try:
        return importlib.import_module(name, package)
    except ModuleNotFoundError:
        return None


class D2A_OT_convert_daz_to_arp(bpy.types.Operator):
    bl_idname = 'object.daz2arp_convert_daz_to_arp'
    bl_label = "Convert Daz armature to AutoRig Pro"
    bl_options = {'REGISTER', 'UNDO'}

    copy_daz_remaining_bones: bpy.props.BoolProperty(
        name="Copy Daz Remaining Bones",
        description="Copy non-body bones such as face and clothing to AutoRig Pro armature",
        default=True,
    )

    remap_daz_corrective_shape_keys: bpy.props.BoolProperty(
        name="Remap Daz Corrective Shape Keys",
        description="Remap the mesh drivers",
        default=True,
    )

    remap_daz_vertex_groups: bpy.props.BoolProperty(
        name="Remap Daz Vertex Groups",
        description="Remap the mesh vertex groups",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        if context.mode != 'OBJECT':
            return False

        active_object = context.active_object
        if active_object is None:
            return False

        if active_object.type != 'ARMATURE':
            return False

        return True

    def execute(self, context):
        daz_armature_object = context.active_object
        daz_armature: bpy.types.Armature = daz_armature_object.data
        daz_has_breast_bones = 'lPectoral' in daz_armature.bones
        arp_armature_object = self._add_arp_rig(context, daz_has_breast_bones)

        bpy.ops.object.mode_set(mode='OBJECT')
        daz_armature_object.select_set(True)

        bpy.ops.object.mode_set(mode='EDIT')
        _snap_arp_ref_bones_to_daz_bones(arp_armature_object, daz_armature_object, self.report)

        bpy.ops.arp.match_to_rig()

        arp_armature_object = next(o for o in context.selected_objects if o.type == 'ARMATURE' and o != daz_armature_object)

        bpy.ops.object.mode_set(mode='EDIT')
        if self.copy_daz_remaining_bones:
            _copy_daz_bones(arp_armature_object, daz_armature_object, self.report)
        _fix_arp_bones(arp_armature_object)

        bpy.ops.object.mode_set(mode='POSE')
        _copy_daz_constraints(arp_armature_object, daz_armature_object, self.report)

        bpy.ops.object.mode_set(mode='OBJECT')
        _fix_daz_corrective_shape_keys(arp_armature_object, daz_armature_object, self.report)

        if self.remap_daz_corrective_shape_keys:
            _remap_daz_corrective_shape_keys(arp_armature_object, daz_armature_object, self.report)

        arp_layer_collection = _find_user_layer_collection(arp_armature_object)

        if self.remap_daz_vertex_groups:
            daz_mesh_object: bpy.types.Object
            for daz_mesh_object in daz_armature_object.children:
                if daz_mesh_object.type != 'MESH':
                    continue

                _remap_daz_vertex_groups(daz_mesh_object, self.report)
                daz_mesh_object.parent = arp_armature_object
                daz_layer_collection = _find_user_layer_collection(daz_mesh_object)
                arp_layer_collection.collection.objects.link(daz_mesh_object)
                daz_layer_collection.collection.objects.unlink(daz_mesh_object)

                for modifier in daz_mesh_object.modifiers:
                    if modifier.type != 'ARMATURE':
                        continue
                    modifier.object = arp_armature_object

        return {'FINISHED'}

    def _add_arp_rig(self, context: bpy.types.Context, add_breast_bones: bool) -> bpy.types.Object:
        arp = _try_import_module('auto_rig_pro-master.auto_rig') or _try_import_module('auto_rig_pro.auto_rig')
        if arp is None:
            self.report({'ERROR'}, "Auto-Rig Pro is not installed.")
            return {'CANCELLED'}

        arp._append_arp(rig_type='human')
        arp._edit_ref()

        armature_object = context.active_object
        armature: bpy.types.Armature = armature_object.data

        def select_bone(name: str, deselect_rest=True):
            if deselect_rest is True:
                for bone in context.selected_editable_bones:
                    bone.select = False
            armature.edit_bones[name].select = True

        # adjust spine
        armature_object.rig_spine_count = 5
        select_bone('root_ref.x')
        arp.set_spine(spine_master_enabled=True)

        # adjust neck
        select_bone('neck_ref.x')
        arp.set_neck(neck_count=2)

        # adjust legs
        select_bone('thigh_ref.l')
        arp.set_toes(True, True, True, True, True)
        select_bone('thigh_ref.r')
        arp.set_toes(True, True, True, True, True)

        # add ears
        arp.set_ears(1)

        # add breast bones
        if add_breast_bones:
            arp.set_breast(True)

        return armature_object


_ReportFunctionType = Callable[[Union[Set[str], Set[int]], str], None]


def _snap_arp_ref_bones_to_daz_bones(arp_armature_object: bpy.types.Object, daz_armature_object: bpy.types.Object, report: Optional[_ReportFunctionType] = None):
    arp_armature: bpy.types.Armature = arp_armature_object.data
    arp_bones = arp_armature.edit_bones
    daz_armature: bpy.types.Armature = daz_armature_object.data
    daz_bones = daz_armature.edit_bones

    for bone_snap_info in ARP_REF_TO_DAZ_BONE_SNAP_INFOS:
        arp_name = bone_snap_info.arp_name
        if arp_name not in arp_bones:
            if report:
                report({'WARNING'}, f"bone {arp_name} not found in {arp_armature_object.name}")
            continue
        arp_side = arp_name[-1] if arp_name[-1] in {'x', 'l', 'r'} else ''
        arp_bone = arp_bones[arp_name]

        daz_name = bone_snap_info.daz_name
        if daz_name not in daz_bones:
            if report:
                report({'WARNING'}, f"bone {daz_name} not found in {daz_armature_object.name}")
            continue
        daz_side = daz_name[0] if daz_name[0] in {'l', 'r'} else ''
        daz_bone = daz_bones[daz_name]

        snap_type = bone_snap_info.snap_type

        if BoneSnapType.BREAST != snap_type:
            arp_bone.roll = daz_bone.roll
        else:
            vector = arp_bone.vector
            arp_bone.head = daz_bone.head
            arp_bone.tail = daz_bone.head + vector

        if BoneSnapType.DISCONNECTED in snap_type:
            arp_bone.use_connect = False

        if BoneSnapType.HEAD in snap_type:
            arp_bone.head = daz_bone.head.copy()

        if BoneSnapType.TAIL in snap_type:
            if BoneSnapType.FLIPPED in snap_type:
                arp_bone.head = daz_bone.tail.copy()
                arp_bone.tail = daz_bone.head.copy()
                arp_bone.roll += math.pi
            else:
                arp_bone.tail = daz_bone.tail.copy()

        if BoneSnapType.FOOT_PROXIMAL in snap_type:
            arp_bone.tail = daz_bone.head.copy()
            arp_bone.head = (2 * daz_bone.head) - (1 * daz_bone.tail)

        if BoneSnapType.SHIN in snap_type:
            arp_bone.tail = daz_bones[f'{daz_side}Foot'].head

        if BoneSnapType.ANKLE in snap_type:
            arp_bone.tail = daz_bones[f'{daz_side}Toe'].head.copy()
            arp_foot_heel_ref = arp_bones[f'foot_heel_ref.{arp_side}']
            arp_foot_bank_01_ref = arp_bones[f'foot_bank_01_ref.{arp_side}']
            arp_foot_bank_02_ref = arp_bones[f'foot_bank_02_ref.{arp_side}']

            daz_metatarsals = daz_bones[f'{daz_side}Metatarsals']
            daz_foot_vector: Vector = daz_metatarsals.tail - daz_metatarsals.head
            daz_foot_vector.z = 0
            daz_foot_vector.normalize()
            daz_foot_orthogonal_vector = Vector((daz_foot_vector.y, -daz_foot_vector.x, 0.0))

            arp_foot_heel_ref_length = arp_foot_heel_ref.length
            arp_foot_heel_ref.head = Vector((daz_metatarsals.head.x, daz_metatarsals.head.y, arp_foot_heel_ref.head.z))
            arp_foot_heel_ref.head -= 0.05 * daz_foot_vector  # shift 0.05 m
            arp_foot_heel_ref.tail = arp_foot_heel_ref.head + daz_foot_vector * arp_foot_heel_ref_length

            daz_smalltoe4 = daz_bones[f'{daz_side}SmallToe4']
            arp_foot_bank_01_ref.head, _ = mathutils.geometry.intersect_point_line(daz_smalltoe4.head, arp_foot_heel_ref.head, arp_foot_heel_ref.head - daz_foot_orthogonal_vector)
            arp_foot_bank_01_ref.head -= 0.005 * daz_foot_orthogonal_vector  # shift 0.005 m
            arp_foot_bank_01_ref.tail = arp_foot_bank_01_ref.head + daz_foot_vector * arp_foot_heel_ref_length

            daz_bigtoe = daz_bones[f'{daz_side}BigToe']
            arp_foot_bank_02_ref.head, _ = mathutils.geometry.intersect_point_line(daz_bigtoe.head, arp_foot_heel_ref.head, arp_foot_heel_ref.head + daz_foot_orthogonal_vector)
            arp_foot_bank_02_ref.head += 0.01 * daz_foot_orthogonal_vector  # shift 0.01 m
            arp_foot_bank_02_ref.tail = arp_foot_bank_02_ref.head + daz_foot_vector * arp_foot_heel_ref_length


def _copy_daz_bones(arp_armature_object: bpy.types.Object, daz_armature_object: bpy.types.Object, report: Optional[_ReportFunctionType] = None):
    arp_armature: bpy.types.Armature = arp_armature_object.data
    arp_bones = arp_armature.edit_bones
    daz_armature: bpy.types.Armature = daz_armature_object.data
    daz_bones = daz_armature.edit_bones
    ignore_bone_names = set(DAZ_TO_ARP_VERTEXGROUPS.keys())
    ignore_bone_names.add('lMetatarsals')
    ignore_bone_names.add('rMetatarsals')

    copy_root_bones: Dict[bpy.types.EditBone, bpy.types.EditBone] = dict()

    def find_child(daz_bone: bpy.types.EditBone, arp_bone: Optional[bpy.types.EditBone] = None):
        if daz_bone.name in DAZ_TO_ARP_VERTEXGROUPS:
            arp_bone = arp_bones[DAZ_TO_ARP_VERTEXGROUPS[daz_bone.name]]

        if daz_bone.name not in ignore_bone_names:
            copy_root_bones[daz_bone] = arp_bone
            return

        for daz_child_bone in daz_bone.children:
            find_child(daz_child_bone, arp_bone)

    find_child(daz_bones['pelvis'])
    find_child(daz_bones['abdomenLower'])

    def duplicate_bones_recursively(daz_bone: bpy.types.EditBone, arp_parent_bone: bpy.types.EditBone):
        new_arp_bone = arp_bones.new(daz_bone.name)
        new_arp_bone.parent = arp_parent_bone
        new_arp_bone.head = daz_bone.head
        new_arp_bone.tail = daz_bone.tail
        new_arp_bone.roll = daz_bone.roll
        new_arp_bone.use_deform = daz_bone.use_deform
        new_arp_bone.use_connect = daz_bone.use_connect
        new_arp_bone.layers = [i in {24} for i in range(32)]

        for daz_child_bone in daz_bone.children:
            duplicate_bones_recursively(daz_child_bone, new_arp_bone)

    for daz_bone, arp_bone in copy_root_bones.items():
        duplicate_bones_recursively(daz_bone, arp_bone)


def _fix_arp_bones(arp_armature_object: bpy.types.Object):
    arp_armature: bpy.types.Armature = arp_armature_object.data
    arp_bones = arp_armature.edit_bones

    # connect the hand bones to get the correct angle for Corrective Shape Keys
    arp_bones['hand.l'].use_inherit_rotation = True
    arp_bones['hand.r'].use_inherit_rotation = True


def _copy_daz_constraints(arp_armature_object: bpy.types.Object, daz_armature_object: bpy.types.Object, report: Optional[_ReportFunctionType] = None):
    arp_bones = arp_armature_object.pose.bones
    daz_bones = daz_armature_object.pose.bones

    for arp_bone in arp_bones:
        roll_type, daz_bone_name, arp_parent_bone_name = ARP_BONE_LIMIT_ROTATION_BASES.get(arp_bone.name, (BoneRollType.ROLL_0, None, None))

        daz_bone: bpy.types.PoseBone
        if daz_bone_name is not None:
            daz_bone = daz_bones[daz_bone_name]
        elif arp_bone.name in daz_bones:
            daz_bone = daz_bones[arp_bone.name]
        else:
            continue

        for daz_constraint in daz_bone.constraints:
            if daz_constraint.type != 'LIMIT_ROTATION':
                continue

            dc: bpy.types.LimitRotationConstraint = daz_constraint
            ac: bpy.types.LimitRotationConstraint = arp_bone.constraints.new(type='LIMIT_ROTATION')
            ac.name = dc.name
            ac.use_limit_x, ac.min_x, ac.max_x = dc.use_limit_x, dc.min_x, dc.max_x
            ac.use_limit_y, ac.min_y, ac.max_y = dc.use_limit_y, dc.min_y, dc.max_y
            ac.use_limit_z, ac.min_z, ac.max_z = dc.use_limit_z, dc.min_z, dc.max_z
            ac.euler_order = dc.euler_order
            ac.use_transform_limit = dc.use_transform_limit

            if arp_parent_bone_name is None:
                ac.owner_space = dc.owner_space
                continue

            # TODO calculate the angle considering bone orientation and parent angle difference.
            continue
            arp_parent_bone = arp_bones[arp_parent_bone_name]
            arp_parent_vector: Vector = arp_parent_bone.vector
            daz_parent_vector: Vector = daz_bone.parent.vector
            base_euler: Euler = arp_bone.vector.rotation_difference(daz_bone.vector).to_euler()
            parent_euler: Euler = arp_parent_bone.vector.rotation_difference(daz_bone.parent.vector).to_euler()
            daz_euler: Euler = arp_bone.vector.rotation_difference(daz_bone.parent.vector).to_euler()
            ac.min_x += parent_euler.x - base_euler.x  # + daz_euler.x
            ac.max_x += parent_euler.x - base_euler.x  # + daz_euler.x
            ac.min_y += parent_euler.y - base_euler.y  # + daz_euler.y
            ac.max_y += parent_euler.y - base_euler.y  # + daz_euler.y
            ac.min_z += parent_euler.z - base_euler.z  # + daz_euler.z
            ac.max_z += parent_euler.z - base_euler.z  # + daz_euler.z

            ac.owner_space = 'CUSTOM'
            ac.space_object = arp_armature_object
            ac.space_subtarget = arp_parent_bone_name


def _fix_daz_corrective_shape_keys(arp_armature_object: bpy.types.Object, daz_armature_object: bpy.types.Object, report: Optional[_ReportFunctionType] = None):
    class NameCollector(ast.NodeVisitor):
        def __init__(self):
            self._names: Set[str] = set()

        def visit(self, node: ast.AST):
            if isinstance(node, ast.Name):
                name_node: ast.Name = node
                self._names.add(name_node.id)

            return self.generic_visit(node)

        def get_names(self) -> Set[str]:
            return self._names

    mesh_object: bpy.types.Object
    for mesh_object in daz_armature_object.children_recursive:
        if mesh_object.type != 'MESH':
            continue

        mesh: bpy.types.Mesh = mesh_object.data
        for fcurve in mesh.shape_keys.animation_data.drivers:
            driver = fcurve.driver
            name_collector = NameCollector()
            name_collector.visit(ast.parse(driver.expression))
            expression_names = name_collector.get_names()

            for variable in driver.variables:
                if variable.name not in expression_names:
                    # remove unused variable
                    driver.variables.remove(variable)
                    continue

            if 'ForeArmFwd_135_L' in fcurve.data_path:
                # fix DazToBlender bug https://github.com/daz3d/DazToBlender/issues/151
                driver.expression = driver.expression.replace("57.3),0.0,135.0,1,135.0)", "57.3),75,135,1,60.0)")


def _remap_daz_corrective_shape_keys(arp_armature_object: bpy.types.Object, daz_armature_object: bpy.types.Object, report: Optional[_ReportFunctionType] = None):
    mesh_object: bpy.types.Object
    for mesh_object in daz_armature_object.children_recursive:
        if mesh_object.type != 'MESH':
            continue

        mesh: bpy.types.Mesh = mesh_object.data
        for fcurve in mesh.shape_keys.animation_data.drivers:
            if not fcurve.data_path.startswith('key_blocks["pJCM'):
                continue

            driver = fcurve.driver
            variable_names_to_ignore: Set[str] = set()

            for variable in driver.variables:
                if variable.type != 'TRANSFORMS':
                    continue

                if variable.name in variable_names_to_ignore:
                    continue

                target = variable.targets[0]
                daz_bone_name = target.bone_target
                arp_bone_name = DAZ_TO_ARP_VERTEXGROUPS.get(daz_bone_name)
                if arp_bone_name is None:
                    if report:
                        report({'WARNING'}, f'Not found {daz_bone_name}')
                    continue

                bone_roll_info = ARP_REF_BONE_ROLL_INFOS.get(arp_bone_name)

                if bone_roll_info is None:
                    continue

                target.id = arp_armature_object
                target.bone_target = arp_bone_name if bone_roll_info.override_bone_name is None else bone_roll_info.override_bone_name

                if BoneRollType.ROLL_0 == bone_roll_info.roll_type:
                    continue

                if BoneRollType.ROLL_ADD_BONES in bone_roll_info.roll_type:
                    target_variable_names: List[str] = [variable.name]
                    for add_bone_name in bone_roll_info.add_bone_names:
                        new_variable = driver.variables.new()
                        new_variable.type = variable.type
                        new_variable.targets[0].id = variable.targets[0].id
                        new_variable.targets[0].transform_type = variable.targets[0].transform_type
                        new_variable.targets[0].transform_space = variable.targets[0].transform_space

                        new_variable.targets[0].bone_target = add_bone_name
                        target_variable_names.append(new_variable.name)

                    driver.expression = driver.expression.replace(variable.name, f"({'+'.join(target_variable_names)})")
                    variable_names_to_ignore.update(target_variable_names)

                def invert_expression():
                    driver.expression = driver.expression.replace(variable.name, f'(-{variable.name})')

                def set_roll_axis(transform_type: str, invert: bool = False):
                    target.transform_type = transform_type
                    if invert:
                        invert_expression()

                if BoneRollType.ROLL_DIFFERENCE in bone_roll_info.roll_type:
                    variable.type = 'ROTATION_DIFF'
                    variable.targets[1].id = arp_armature_object
                    variable.targets[1].bone_target = bone_roll_info.difference_bone_name
                    if bone_roll_info.difference_invert:
                        invert_expression()

                elif BoneRollType.ROLL_90 in bone_roll_info.roll_type:
                    # +90: X>+Z, Z>-X
                    if target.transform_type == 'ROT_X':
                        set_roll_axis('ROT_Z')
                    elif target.transform_type == 'ROT_Z':
                        set_roll_axis('ROT_X', invert=True)

                elif BoneRollType.ROLL_180 in bone_roll_info.roll_type:
                    # +180: X>-X, Z>-Z
                    if target.transform_type == 'ROT_X':
                        set_roll_axis('ROT_X', invert=True)
                    elif target.transform_type == 'ROT_Z':
                        set_roll_axis('ROT_Z', invert=True)

                elif BoneRollType.ROLL_270 in bone_roll_info.roll_type:
                    # +270: X>-Z, Z>+X
                    if target.transform_type == 'ROT_X':
                        set_roll_axis('ROT_Z', invert=True)
                    elif target.transform_type == 'ROT_Z':
                        set_roll_axis('ROT_X')


def _remap_daz_vertex_groups(daz_mesh_object: bpy.types.Object, report: Optional[_ReportFunctionType] = None):
    for daz_name, arp_name in DAZ_TO_ARP_VERTEXGROUPS.items():
        try:
            vertex_group = daz_mesh_object.vertex_groups[daz_name]
            vertex_group.name = arp_name
            vertex_group.lock_weight = True
        except:
            if report:
                report({'WARNING'}, f"vertext group {daz_name} not found in {daz_mesh_object.name}")

    def combine_vertex_group(arp_vertex_group_name: str, daz_vertex_group_name: str):
        try:
            modifier: bpy.types.VertexWeightMixModifier = daz_mesh_object.modifiers.new(arp_vertex_group_name, type='VERTEX_WEIGHT_MIX')
            modifier.vertex_group_a = arp_vertex_group_name
            modifier.vertex_group_b = daz_vertex_group_name
            modifier.mix_mode = 'ADD'
            modifier.mix_set = 'ALL'
            bpy.ops.object.modifier_apply({'object': daz_mesh_object}, modifier=arp_vertex_group_name)
        except:
            logging.error(traceback.format_exc())
            if report:
                report({'WARNING'}, f"{daz_vertex_group_name} not merged in {daz_mesh_object.name}")
            bpy.ops.object.modifier_remove({'object': daz_mesh_object}, modifier=arp_vertex_group_name)

    # some bones are unavailable in ARP
    # so merge them with adjacent bones
    combine_vertex_group('foot.l', 'lMetatarsals')
    combine_vertex_group('foot.r', 'rMetatarsals')


def _find_user_layer_collection(target_object: bpy.types.Object) -> Optional[bpy.types.LayerCollection]:
    context: bpy.types.Context = bpy.context
    scene_layer_collection: bpy.types.LayerCollection = context.view_layer.layer_collection

    def find_layer_collection_by_name(layer_collection: bpy.types.LayerCollection, name: str) -> Optional[bpy.types.LayerCollection]:
        if layer_collection.name == name:
            return layer_collection

        child_layer_collection: bpy.types.LayerCollection
        for child_layer_collection in layer_collection.children:
            found = find_layer_collection_by_name(child_layer_collection, name)
            if found is not None:
                return found

        return None

    user_collection: bpy.types.Collection
    for user_collection in target_object.users_collection:
        found = find_layer_collection_by_name(scene_layer_collection, user_collection.name)
        if found is not None:
            return found

    return None


def _menu_func(self, _context):
    self.layout.operator(D2A_OT_convert_daz_to_arp.bl_idname, text=D2A_OT_convert_daz_to_arp.bl_label)


def _erc_keyed(var, min, max, normalized_dist, dist):
    """Converts difference to a 0 to 1 range
    see: https://github.com/daz3d/DazToBlender/blob/1bcb95f6e0e4c901a1f99c350e6334cfae2cf96c/Blender/appdata_common/Blender%20Foundation/Blender/BLENDER_VERSION/scripts/addons/DTB/__init__.py#L294
    """
    if dist < 0:
        if max <= var <= min:
            return abs((var - min) / dist)
        elif max >= var:
            return 1
        else:
            return 0
    if min <= var <= max:
        return abs((var - min * normalized_dist) / dist)
    elif max <= var:
        return 1
    else:
        return 0


@bpy.app.handlers.persistent
def _load_handler(dummy):
    dns = bpy.app.driver_namespace
    if not hasattr(dns, 'erc_keyed'):
        dns['erc_keyed'] = _erc_keyed


def register():
    """Register and add to the "object" menu (required to also use F3 search "Simple Object Operator" for quick access)"""
    _load_handler(None)
    bpy.app.handlers.load_post.append(_load_handler)
    bpy.utils.register_class(D2A_OT_convert_daz_to_arp)
    bpy.types.VIEW3D_MT_object.append(_menu_func)


def unregister():
    bpy.types.VIEW3D_MT_object.remove(_menu_func)
    bpy.utils.unregister_class(D2A_OT_convert_daz_to_arp)
    bpy.app.handlers.load_post.remove(_load_handler)


if __name__ == '__main__':
    register()


DAZ_TO_ARP_VERTEXGROUPS = {
    "pelvis": "root.x",
    "lThighBend": "thigh_twist.l",
    "lThighTwist": "thigh_stretch.l",
    "lShin": "leg_stretch.l",
    # "": "leg_twist.l",
    "lFoot": "foot.l",
    "lToe": "toes_01.l",
    "lSmallToe4": "c_toes_pinky2.l",
    "lSmallToe4_2": "c_toes_pinky3.l",
    "lSmallToe3": "c_toes_ring2.l",
    "lSmallToe3_2": "c_toes_ring3.l",
    "lSmallToe2": "c_toes_middle2.l",
    "lSmallToe2_2": "c_toes_middle3.l",
    "lSmallToe1": "c_toes_index2.l",
    "lSmallToe1_2": "c_toes_index3.l",
    "lBigToe": "c_toes_thumb1.l",
    "lBigToe_2": "c_toes_thumb2.l",

    "rThighBend": "thigh_twist.r",
    "rThighTwist": "thigh_stretch.r",
    "rShin": "leg_stretch.r",
    # "": "leg_twist.r",
    "rFoot": "foot.r",
    "rToe": "toes_01.r",
    "rSmallToe4": "c_toes_pinky2.r",
    "rSmallToe4_2": "c_toes_pinky3.r",
    "rSmallToe3": "c_toes_ring2.r",
    "rSmallToe3_2": "c_toes_ring3.r",
    "rSmallToe2": "c_toes_middle2.r",
    "rSmallToe2_2": "c_toes_middle3.r",
    "rSmallToe1": "c_toes_index2.r",
    "rSmallToe1_2": "c_toes_index3.r",
    "rBigToe": "c_toes_thumb1.r",
    "rBigToe_2": "c_toes_thumb2.r",

    "abdomenLower": "spine_01.x",
    "abdomenUpper": "spine_02.x",
    "chestLower": "spine_03.x",
    "chestUpper": "spine_04.x",

    "lCollar": "shoulder.l",
    "lShldrBend": "c_arm_twist_offset.l",
    "lShldrTwist": "arm_stretch.l",
    "lForearmBend": "forearm_stretch.l",
    "lForearmTwist": "forearm_twist.l",
    "lHand": "hand.l",
    "lThumb1": "thumb1.l",
    "lThumb2": "c_thumb2.l",
    "lThumb3": "c_thumb3.l",
    "lCarpal1": "c_index1_base.l",
    "lIndex1": "index1.l",
    "lIndex2": "c_index2.l",
    "lIndex3": "c_index3.l",
    "lCarpal2": "c_middle1_base.l",
    "lMid1": "middle1.l",
    "lMid2": "c_middle2.l",
    "lMid3": "c_middle3.l",
    "lCarpal3": "c_ring1_base.l",
    "lRing1": "ring1.l",
    "lRing2": "c_ring2.l",
    "lRing3": "c_ring3.l",
    "lCarpal4": "c_pinky1_base.l",
    "lPinky1": "pinky1.l",
    "lPinky2": "c_pinky2.l",
    "lPinky3": "c_pinky3.l",

    "rCollar": "shoulder.r",
    "rShldrBend": "c_arm_twist_offset.r",
    "rShldrTwist": "arm_stretch.r",
    "rForearmBend": "forearm_stretch.r",
    "rForearmTwist": "forearm_twist.r",
    "rHand": "hand.r",
    "rThumb1": "thumb1.r",
    "rThumb2": "c_thumb2.r",
    "rThumb3": "c_thumb3.r",
    "rCarpal1": "c_index1_base.r",
    "rIndex1": "index1.r",
    "rIndex2": "c_index2.r",
    "rIndex3": "c_index3.r",
    "rCarpal2": "c_middle1_base.r",
    "rMid1": "middle1.r",
    "rMid2": "c_middle2.r",
    "rMid3": "c_middle3.r",
    "rCarpal3": "c_ring1_base.r",
    "rRing1": "ring1.r",
    "rRing2": "c_ring2.r",
    "rRing3": "c_ring3.r",
    "rCarpal4": "c_pinky1_base.r",
    "rPinky1": "pinky1.r",
    "rPinky2": "c_pinky2.r",
    "rPinky3": "c_pinky3.r",

    "neckLower": "c_subneck_1.x",
    "neckUpper": "neck.x",
    "head": "head.x",

    "lEar": "c_ear_01.l",
    "rEar": "c_ear_01.r",
    "lPectoral": "c_breast_01.l",
    "rPectoral": "c_breast_01.r",
}


class BoneRollType(Flag):
    ROLL_0 = 0
    ROLL_90 = 1
    ROLL_180 = 2
    ROLL_270 = 4
    ROLL_DIFFERENCE = 8
    ROLL_ADD_BONES = 16

    ROLL_SPINE = ROLL_0 | ROLL_ADD_BONES


@dataclass
class BoneRollInfo:
    roll_type: BoneRollType
    override_bone_name: str = None
    difference_bone_name: str = None
    difference_invert: bool = False
    add_bone_names: List[str] = None


ARP_REF_BONE_ROLL_INFOS: Dict[str, BoneRollInfo] = {
    'root.x': BoneRollInfo(BoneRollType.ROLL_0, 'c_root.x'),
    'spine_01.x': BoneRollInfo(BoneRollType.ROLL_SPINE, 'c_spine_01.x', add_bone_names=['spine_01_cns.x']),
    'spine_02.x': BoneRollInfo(BoneRollType.ROLL_SPINE, 'c_spine_02.x', add_bone_names=['spine_02_cns.x']),
    'spine_03.x': BoneRollInfo(BoneRollType.ROLL_SPINE, 'c_spine_03.x', add_bone_names=['spine_03_cns.x']),

    'thigh_twist.l': BoneRollInfo(BoneRollType.ROLL_90),
    'thigh_twist.r': BoneRollInfo(BoneRollType.ROLL_270),
    'leg_stretch.l': BoneRollInfo(BoneRollType.ROLL_90),
    'leg_stretch.r': BoneRollInfo(BoneRollType.ROLL_270),
    'foot.l': BoneRollInfo(BoneRollType.ROLL_0,),
    'foot.r': BoneRollInfo(BoneRollType.ROLL_0,),
    'toes_01.l': BoneRollInfo(BoneRollType.ROLL_180),
    'toes_01.r': BoneRollInfo(BoneRollType.ROLL_180),
    'c_toes_thumb1.r': BoneRollInfo(BoneRollType.ROLL_0),
    'c_toes_thumb1.l': BoneRollInfo(BoneRollType.ROLL_0),

    'shoulder.l': BoneRollInfo(BoneRollType.ROLL_0),
    'shoulder.r': BoneRollInfo(BoneRollType.ROLL_180),
    'c_arm_twist_offset.l': BoneRollInfo(BoneRollType.ROLL_0, 'arm_twist.l'),
    'c_arm_twist_offset.r': BoneRollInfo(BoneRollType.ROLL_180, 'arm_twist.r'),
    'forearm_stretch.l':  BoneRollInfo(BoneRollType.ROLL_270),
    'forearm_stretch.r':  BoneRollInfo(BoneRollType.ROLL_270),
    'hand.l': BoneRollInfo(BoneRollType.ROLL_0),
    'hand.r': BoneRollInfo(BoneRollType.ROLL_180),

    'c_subneck_1.x': BoneRollInfo(BoneRollType.ROLL_0),
    'neck.x': BoneRollInfo(BoneRollType.ROLL_0, 'c_neck.x'),
    'head.x': BoneRollInfo(BoneRollType.ROLL_0, 'c_head.x'),
}

ARP_BONE_LIMIT_ROTATION_BASES = {
    # 'c_spine_01.x': (BoneRollType.ROLL_0, 'abdomenLower', None),
    # 'c_spine_02.x': (BoneRollType.ROLL_0, 'abdomenUpper', None),
    # 'c_spine_03.x': (BoneRollType.ROLL_0, 'chestLower', None),
    # 'c_spine_04.x': (BoneRollType.ROLL_0, 'chestUpper', None),
    # 'c_shoulder.l': (BoneRollType.ROLL_0, 'lCollar', None),
    # 'c_arm_fk.l': (BoneRollType.ROLL_0, 'lShldrBend', None),
    # 'c_arm_ik.l': (BoneRollType.ROLL_0, 'lShldrBend', None),
    # 'c_shoulder.r': (BoneRollType.ROLL_0, 'rCollar', None),
    # 'c_arm_fk.r': (BoneRollType.ROLL_0, 'rShldrBend', None),
    # 'c_arm_ik.r': (BoneRollType.ROLL_0, 'rShldrBend', None),
}


class BoneSnapType(Flag):
    HEAD = 1
    TAIL = 2
    DISCONNECTED = 4
    FLIPPED = 8
    FOOT_PROXIMAL = 16
    SHIN = 32
    ANKLE = 64
    BREAST = 128

    HEAD_DISCONNECTED = HEAD | DISCONNECTED
    HEAD_AND_TAIL = HEAD | TAIL
    HEAD_AND_TAIL_DISCONNECTED = HEAD_AND_TAIL | DISCONNECTED
    TAIL_AND_HEAD = HEAD_AND_TAIL | FLIPPED
    LEG_SHIN = HEAD | SHIN
    FOOT_ANKLE = HEAD_AND_TAIL_DISCONNECTED | ANKLE


@dataclass
class BoneSnapInfo:
    snap_type: BoneSnapType
    arp_name: str
    daz_name: str


ARP_REF_TO_DAZ_BONE_SNAP_INFOS: List[BoneSnapInfo] = list(reversed([
    BoneSnapInfo(BoneSnapType.TAIL_AND_HEAD, 'root_ref.x', 'pelvis'),
    BoneSnapInfo(BoneSnapType.HEAD_DISCONNECTED, 'spine_01_ref.x', 'abdomenLower'),
    BoneSnapInfo(BoneSnapType.HEAD, 'spine_02_ref.x', 'abdomenUpper'),
    BoneSnapInfo(BoneSnapType.HEAD, 'spine_03_ref.x', 'chestLower'),
    BoneSnapInfo(BoneSnapType.HEAD_AND_TAIL, 'spine_04_ref.x', 'chestUpper'),

    BoneSnapInfo(BoneSnapType.HEAD, 'thigh_ref.l', 'lThighBend'),
    BoneSnapInfo(BoneSnapType.LEG_SHIN, 'leg_ref.l', 'lShin'),
    BoneSnapInfo(BoneSnapType.FOOT_ANKLE, 'foot_ref.l', 'lFoot'),
    BoneSnapInfo(BoneSnapType.HEAD_AND_TAIL_DISCONNECTED, 'toes_ref.l', 'lToe'),
    BoneSnapInfo(BoneSnapType.HEAD, 'toes_thumb1_ref.l', 'lBigToe'),
    BoneSnapInfo(BoneSnapType.HEAD_AND_TAIL, 'toes_thumb2_ref.l', 'lBigToe_2'),
    BoneSnapInfo(BoneSnapType.FOOT_PROXIMAL, 'toes_index1_ref.l', 'lSmallToe1'),
    BoneSnapInfo(BoneSnapType.HEAD, 'toes_index2_ref.l', 'lSmallToe1'),
    BoneSnapInfo(BoneSnapType.HEAD_AND_TAIL, 'toes_index3_ref.l', 'lSmallToe1_2'),
    BoneSnapInfo(BoneSnapType.FOOT_PROXIMAL, 'toes_middle1_ref.l', 'lSmallToe2'),
    BoneSnapInfo(BoneSnapType.HEAD, 'toes_middle2_ref.l', 'lSmallToe2'),
    BoneSnapInfo(BoneSnapType.HEAD_AND_TAIL, 'toes_middle3_ref.l', 'lSmallToe2_2'),
    BoneSnapInfo(BoneSnapType.FOOT_PROXIMAL, 'toes_ring1_ref.l', 'lSmallToe3'),
    BoneSnapInfo(BoneSnapType.HEAD, 'toes_ring2_ref.l', 'lSmallToe3'),
    BoneSnapInfo(BoneSnapType.HEAD_AND_TAIL, 'toes_ring3_ref.l', 'lSmallToe3_2'),
    BoneSnapInfo(BoneSnapType.FOOT_PROXIMAL, 'toes_pinky1_ref.l', 'lSmallToe4'),
    BoneSnapInfo(BoneSnapType.HEAD, 'toes_pinky2_ref.l', 'lSmallToe4'),
    BoneSnapInfo(BoneSnapType.HEAD_AND_TAIL, 'toes_pinky3_ref.l', 'lSmallToe4_2'),

    BoneSnapInfo(BoneSnapType.HEAD, 'thigh_ref.r', 'rThighBend'),
    BoneSnapInfo(BoneSnapType.LEG_SHIN, 'leg_ref.r', 'rShin'),
    BoneSnapInfo(BoneSnapType.FOOT_ANKLE, 'foot_ref.r', 'rFoot'),
    BoneSnapInfo(BoneSnapType.HEAD_AND_TAIL_DISCONNECTED, 'toes_ref.r', 'rToe'),
    BoneSnapInfo(BoneSnapType.HEAD, 'toes_thumb1_ref.r', 'rBigToe'),
    BoneSnapInfo(BoneSnapType.HEAD_AND_TAIL, 'toes_thumb2_ref.r', 'rBigToe_2'),
    BoneSnapInfo(BoneSnapType.FOOT_PROXIMAL, 'toes_index1_ref.r', 'rSmallToe1'),
    BoneSnapInfo(BoneSnapType.HEAD, 'toes_index2_ref.r', 'rSmallToe1'),
    BoneSnapInfo(BoneSnapType.HEAD_AND_TAIL, 'toes_index3_ref.r', 'rSmallToe1_2'),
    BoneSnapInfo(BoneSnapType.FOOT_PROXIMAL, 'toes_middle1_ref.r', 'rSmallToe2'),
    BoneSnapInfo(BoneSnapType.HEAD, 'toes_middle2_ref.r', 'rSmallToe2'),
    BoneSnapInfo(BoneSnapType.HEAD_AND_TAIL, 'toes_middle3_ref.r', 'rSmallToe2_2'),
    BoneSnapInfo(BoneSnapType.FOOT_PROXIMAL, 'toes_ring1_ref.r', 'rSmallToe3'),
    BoneSnapInfo(BoneSnapType.HEAD, 'toes_ring2_ref.r', 'rSmallToe3'),
    BoneSnapInfo(BoneSnapType.HEAD_AND_TAIL, 'toes_ring3_ref.r', 'rSmallToe3_2'),
    BoneSnapInfo(BoneSnapType.FOOT_PROXIMAL, 'toes_pinky1_ref.r', 'rSmallToe4'),
    BoneSnapInfo(BoneSnapType.HEAD, 'toes_pinky2_ref.r', 'rSmallToe4'),
    BoneSnapInfo(BoneSnapType.HEAD_AND_TAIL, 'toes_pinky3_ref.r', 'rSmallToe4_2'),

    BoneSnapInfo(BoneSnapType.HEAD, 'shoulder_ref.l', 'lCollar'),
    BoneSnapInfo(BoneSnapType.HEAD, 'arm_ref.l', 'lShldrBend'),
    BoneSnapInfo(BoneSnapType.HEAD, 'forearm_ref.l', 'lForearmBend'),
    BoneSnapInfo(BoneSnapType.HEAD_AND_TAIL, 'hand_ref.l', 'lHand'),
    BoneSnapInfo(BoneSnapType.HEAD, 'thumb1_ref.l', 'lThumb1'),
    BoneSnapInfo(BoneSnapType.HEAD, 'thumb2_ref.l', 'lThumb2'),
    BoneSnapInfo(BoneSnapType.HEAD_AND_TAIL, 'thumb3_ref.l', 'lThumb3'),
    BoneSnapInfo(BoneSnapType.HEAD, 'index1_base_ref.l', 'lCarpal1'),
    BoneSnapInfo(BoneSnapType.HEAD, 'index1_ref.l', 'lIndex1'),
    BoneSnapInfo(BoneSnapType.HEAD, 'index2_ref.l', 'lIndex2'),
    BoneSnapInfo(BoneSnapType.HEAD_AND_TAIL, 'index3_ref.l', 'lIndex3'),
    BoneSnapInfo(BoneSnapType.HEAD, 'middle1_base_ref.l', 'lCarpal2'),
    BoneSnapInfo(BoneSnapType.HEAD, 'middle1_ref.l', 'lMid1'),
    BoneSnapInfo(BoneSnapType.HEAD, 'middle2_ref.l', 'lMid2'),
    BoneSnapInfo(BoneSnapType.HEAD_AND_TAIL, 'middle3_ref.l', 'lMid3'),
    BoneSnapInfo(BoneSnapType.HEAD, 'ring1_base_ref.l', 'lCarpal3'),
    BoneSnapInfo(BoneSnapType.HEAD, 'ring1_ref.l', 'lRing1'),
    BoneSnapInfo(BoneSnapType.HEAD, 'ring2_ref.l', 'lRing2'),
    BoneSnapInfo(BoneSnapType.HEAD_AND_TAIL, 'ring3_ref.l', 'lRing3'),
    BoneSnapInfo(BoneSnapType.HEAD, 'pinky1_base_ref.l', 'lCarpal4'),
    BoneSnapInfo(BoneSnapType.HEAD, 'pinky1_ref.l', 'lPinky1'),
    BoneSnapInfo(BoneSnapType.HEAD, 'pinky2_ref.l', 'lPinky2'),
    BoneSnapInfo(BoneSnapType.HEAD_AND_TAIL, 'pinky3_ref.l', 'lPinky3'),

    BoneSnapInfo(BoneSnapType.HEAD, 'shoulder_ref.r', 'rCollar'),
    BoneSnapInfo(BoneSnapType.HEAD, 'arm_ref.r', 'rShldrBend'),
    BoneSnapInfo(BoneSnapType.HEAD, 'forearm_ref.r', 'rForearmBend'),
    BoneSnapInfo(BoneSnapType.HEAD_AND_TAIL, 'hand_ref.r', 'rHand'),
    BoneSnapInfo(BoneSnapType.HEAD, 'thumb1_ref.r', 'rThumb1'),
    BoneSnapInfo(BoneSnapType.HEAD, 'thumb2_ref.r', 'rThumb2'),
    BoneSnapInfo(BoneSnapType.HEAD_AND_TAIL, 'thumb3_ref.r', 'rThumb3'),
    BoneSnapInfo(BoneSnapType.HEAD, 'index1_base_ref.r', 'rCarpal1'),
    BoneSnapInfo(BoneSnapType.HEAD, 'index1_ref.r', 'rIndex1'),
    BoneSnapInfo(BoneSnapType.HEAD, 'index2_ref.r', 'rIndex2'),
    BoneSnapInfo(BoneSnapType.HEAD_AND_TAIL, 'index3_ref.r', 'rIndex3'),
    BoneSnapInfo(BoneSnapType.HEAD, 'middle1_base_ref.r', 'rCarpal2'),
    BoneSnapInfo(BoneSnapType.HEAD, 'middle1_ref.r', 'rMid1'),
    BoneSnapInfo(BoneSnapType.HEAD, 'middle2_ref.r', 'rMid2'),
    BoneSnapInfo(BoneSnapType.HEAD_AND_TAIL, 'middle3_ref.r', 'rMid3'),
    BoneSnapInfo(BoneSnapType.HEAD, 'ring1_base_ref.r', 'rCarpal3'),
    BoneSnapInfo(BoneSnapType.HEAD, 'ring1_ref.r', 'rRing1'),
    BoneSnapInfo(BoneSnapType.HEAD, 'ring2_ref.r', 'rRing2'),
    BoneSnapInfo(BoneSnapType.HEAD_AND_TAIL, 'ring3_ref.r', 'rRing3'),
    BoneSnapInfo(BoneSnapType.HEAD, 'pinky1_base_ref.r', 'rCarpal4'),
    BoneSnapInfo(BoneSnapType.HEAD, 'pinky1_ref.r', 'rPinky1'),
    BoneSnapInfo(BoneSnapType.HEAD, 'pinky2_ref.r', 'rPinky2'),
    BoneSnapInfo(BoneSnapType.HEAD_AND_TAIL, 'pinky3_ref.r', 'rPinky3'),

    BoneSnapInfo(BoneSnapType.HEAD, 'subneck_1_ref.x', 'neckLower'),
    BoneSnapInfo(BoneSnapType.HEAD, 'neck_ref.x', 'neckUpper'),
    BoneSnapInfo(BoneSnapType.HEAD_AND_TAIL, 'head_ref.x', 'head'),

    BoneSnapInfo(BoneSnapType.HEAD_AND_TAIL, 'ear_01_ref.l', 'lEar'),
    BoneSnapInfo(BoneSnapType.BREAST, 'breast_01_ref.l', 'lPectoral'),
    BoneSnapInfo(BoneSnapType.HEAD_AND_TAIL, 'ear_01_ref.r', 'rEar'),
    BoneSnapInfo(BoneSnapType.BREAST, 'breast_01_ref.r', 'rPectoral'),
]))
