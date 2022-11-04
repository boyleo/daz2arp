# Rename/Remix vertex groups from Daz 3D model to AutoRig Pro
# --- limitations ---
# - no secondary controllers
# - edit limb option on spine for 4 spine bones to be compatible with UE4 mannequin
# - edit limb options on both legs to have toe fingers
# - add breasts / ears (1 bone)

import ast
import logging
import math
from operator import invert
import traceback
from dataclasses import dataclass
from enum import Enum, Flag
from types import ModuleType
from typing import Callable, Dict, List, Optional, Set, Union

import bpy
from mathutils import Vector
import mathutils

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


def erc_keyed(var, min, max, normalized_dist, dist):
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
def load_handler(dummy):
    dns = bpy.app.driver_namespace
    dns["erc_keyed"] = erc_keyed


class Daz2arp_vertex_group_remap(bpy.types.Operator):
    """Remap Daz vertex group to AutoRig Pro"""
    bl_idname = "mesh.daz2arp_vertex_group_remap"
    bl_label = "Remap Daz Vertex Groups to AutoRig Pro"

    @classmethod
    def poll(cls, context):
        return any(o.type == 'MESH' for o in context.selected_objects)

    def combine_vertex_group(self, daz_object: bpy.types.Object, arp_vertex_group_name: str, daz_vertex_group_name: str):
        try:
            modifier: bpy.types.VertexWeightMixModifier = daz_object.modifiers.new(arp_vertex_group_name, type='VERTEX_WEIGHT_MIX')
            modifier.vertex_group_a = arp_vertex_group_name
            modifier.vertex_group_b = daz_vertex_group_name
            modifier.mix_mode = 'ADD'
            modifier.mix_set = 'ALL'
            bpy.ops.object.modifier_apply(modifier=arp_vertex_group_name)
        except:
            logging.error(traceback.format_exc())
            self.report({'WARNING'}, f"{daz_vertex_group_name} not merged in {daz_object.name}")
            bpy.ops.object.modifier_remove(modifier=arp_vertex_group_name)

    def execute(self, context):
        # remap each vertex group
        for obj in context.selected_objects:
            if obj.type != 'MESH':
                continue

            for daz_name, arp_name in DAZ_TO_ARP_VERTEXGROUPS.items():
                try:
                    obj.vertex_groups[daz_name].name = arp_name
                    obj.vertex_groups[arp_name].lock_weight = True
                    self.report({'INFO'}, f"changed vertex group {daz_name} to {arp_name}")
                except:
                    self.report({'WARNING'}, f"vertext group {daz_name} not found in {obj.name}")

            # some bones are unavailable in ARP
            # so merge them with adjacent bones
            self.combine_vertex_group(obj, "foot.l", "lMetatarsals")
            self.combine_vertex_group(obj, "foot.r", "rMetatarsals")
            # self.combine_vertex_group(obj, "spine_03.x", "chestUpper")

        return {'FINISHED'}


ReportFunctionType = Callable[[Union[Set[str], Set[int]], str], None]


def try_import_module(name: str, package: Optional[str] = None) -> Optional[ModuleType]:
    import importlib
    try:
        return importlib.import_module(name, package)
    except ModuleNotFoundError:
        return None


class D2A_OT_add_rig(bpy.types.Operator):
    bl_idname = "mesh.daz2arp_add_rig"
    bl_label = "XXXXXXXXXXXXXx"
    bl_options = {'REGISTER', 'UNDO'}

    def _add_arp_rig(self, context: bpy.types.Context) -> bpy.types.Object:
        arp = try_import_module('auto_rig_pro-master.auto_rig') or try_import_module('auto_rig_pro.auto_rig')
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
        # arp.set_leg_auto_ik_roll(False)
        select_bone('thigh_ref.r')
        arp.set_toes(True, True, True, True, True)
        # arp.set_leg_auto_ik_roll(False)

        return armature_object

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
        arp_armature_object = self._add_arp_rig(context)

        bpy.ops.object.mode_set(mode='OBJECT')
        daz_armature_object.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        snap_arp_ref_bones_to_daz_bones(arp_armature_object, daz_armature_object, self.report)

        bpy.ops.arp.match_to_rig()

        return {'FINISHED'}


def snap_arp_ref_bones_to_daz_bones(arp_armature_object: bpy.types.Object, daz_armature_object: bpy.types.Object, report: Optional[ReportFunctionType] = None):
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

        arp_bone.align_roll(daz_bone.z_axis)

        snap_type = bone_snap_info.snap_type
        if BoneSnapType.DISCONNECTED in snap_type:
            arp_bone.use_connect = False

        if BoneSnapType.HEAD in snap_type:
            arp_bone.head = daz_bone.head.copy()
            # arp_bone.roll = daz_bone.roll
            # arp_bone.align_orientation(daz_bone)

        if BoneSnapType.TAIL in snap_type:
            if BoneSnapType.FLIPPED in snap_type:
                arp_bone.head = daz_bone.tail.copy()
                arp_bone.tail = daz_bone.head.copy()
                arp_bone.align_roll(-daz_bone.z_axis)
            else:
                arp_bone.tail = daz_bone.tail.copy()

        if BoneSnapType.FOOT_PROXIMAL in snap_type:
            arp_bone.tail = daz_bone.head.copy()
            arp_bone.head = (2 * daz_bone.head) - (1 * daz_bone.tail)

        if BoneSnapType.SHIN in snap_type:
            daz_child_bone = daz_bone.children[0]
            daz_thightwist = daz_bones[f'{daz_side}ThighTwist']
            arp_bone.head = (daz_bone.head + daz_thightwist.tail) / 2
            arp_bone.tail = (2 * daz_child_bone.head) - (1 * daz_child_bone.tail)
            arp_bone.roll += math.pi / 2

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


class Daz2arp_bone_snap(bpy.types.Operator):
    """Snap AutoRig Pro reference bones to Daz"""
    bl_idname = "mesh.daz2arp_bone_snap"
    bl_label = "Copy Bones"

    @classmethod
    def poll(cls, context):
        if context.mode != 'OBJECT':
            return False

        active_object = context.active_object
        if active_object is None:
            return False

        if active_object.type != 'ARMATURE':
            return False

        # ARP objects have 'als' custom property.
        if 'als' not in active_object:
            return False

        # 2 armature objects must be selected.
        return sum(1 for o in context.selected_objects if o.type == 'ARMATURE') == 2

    def execute(self, context):
        arp_armature_object = context.active_object
        daz_armature_object = next(o for o in context.selected_objects if o.type == 'ARMATURE' and o != arp_armature_object)

        bpy.ops.object.mode_set(mode='EDIT')
        copy_daz_bones(arp_armature_object, daz_armature_object, self.report)
        fix_arp_bones(arp_armature_object, daz_armature_object, self.report)

        bpy.ops.object.mode_set(mode='POSE')
        # copy_daz_constraints(arp_armature_object, daz_armature_object, self.report)

        bpy.ops.object.mode_set(mode='OBJECT')
        fix_daz_corrective_shape_keys(arp_armature_object, daz_armature_object, self.report)
        adjust_daz_corrective_shape_keys(arp_armature_object, daz_armature_object, self.report)

        return {'FINISHED'}


class NameGather(ast.NodeVisitor):
    def __init__(self):
        self._names: Set[str] = set()

    def visit(self, node: ast.AST):
        if isinstance(node, ast.Name):
            name_node: ast.Name = node
            self._names.add(name_node.id)

        return self.generic_visit(node)

    def get_names(self) -> Set[str]:
        return self._names

def fix_daz_corrective_shape_keys(arp_armature_object: bpy.types.Object, daz_armature_object: bpy.types.Object, report: Optional[ReportFunctionType] = None):

    mesh_object: bpy.types.Object
    for mesh_object in daz_armature_object.children_recursive:
        if mesh_object.type != 'MESH':
            continue

        mesh: bpy.types.Mesh = mesh_object.data
        for fcurve in mesh.shape_keys.animation_data.drivers:
            driver = fcurve.driver
            name_gather = NameGather()
            name_gather.visit(ast.parse(driver.expression))
            expression_names = name_gather.get_names()

            for variable in driver.variables:
                if variable.name not in expression_names:
                    # remove unused variable
                    driver.variables.remove(variable)
                    continue
            
            if 'ForeArmFwd_135_L' in fcurve.data_path:
                # fix DazToBlender bug
                driver.expression = driver.expression.replace("57.3),0.0,135.0,1,135.0)", "57.3),75,135,1,60.0)")


def adjust_daz_corrective_shape_keys(arp_armature_object: bpy.types.Object, daz_armature_object: bpy.types.Object, report: Optional[ReportFunctionType] = None):
    arp_armature: bpy.types.Armature = arp_armature_object.data
    arp_bones = arp_armature.bones
    daz_armature: bpy.types.Armature = daz_armature_object.data
    daz_bones = daz_armature.bones

    mesh_object: bpy.types.Object
    for mesh_object in daz_armature_object.children_recursive:
        if mesh_object.type != 'MESH':
            continue

        mesh: bpy.types.Mesh = mesh_object.data
        for fcurve in mesh.shape_keys.animation_data.drivers:
            if not fcurve.data_path.startswith('key_blocks["pJCM'):
                continue

            driver = fcurve.driver
            for variable in driver.variables:
                if variable.type != 'TRANSFORMS':
                    continue

                target = variable.targets[0]
                daz_bone_name = target.bone_target
                arp_bone_name = DAZ_TO_ARP_VERTEXGROUPS.get(daz_bone_name)
                if arp_bone_name is None:
                    report({'WARNING'}, f'Not found {daz_bone_name}')
                    continue

                # print(f'{fcurve.data_path}: {daz_bone_name},\t{target.transform_type},\t{variable.name},\t{driver.expression}')

                bone_roll_info = ARP_REF_BONE_ROLL_INFOS.get(arp_bone_name)

                if bone_roll_info is None:
                    continue

                target.id = arp_armature_object
                target.bone_target = arp_bone_name if bone_roll_info.override_bone_name is None else bone_roll_info.override_bone_name

                if bone_roll_info.roll_type == BoneRollType.ROLL_0:
                    continue

                def invert_expression():
                    driver.expression = driver.expression.replace(variable.name, f'(-{variable.name})')

                def set_roll_axis(transform_type: str, invert: bool = False):
                    target.transform_type = transform_type
                    if invert:
                        invert_expression()

                if bone_roll_info.roll_type == BoneRollType.ROLL_DIFFERENCE:
                    variable.type = 'ROTATION_DIFF'
                    variable.targets[1].id = arp_armature_object
                    variable.targets[1].bone_target = bone_roll_info.difference_bone_name
                    if bone_roll_info.difference_invert:
                        invert_expression()

                elif bone_roll_info.roll_type == BoneRollType.ROLL_90:
                    # +90: X>+Z, Z>-X
                    if target.transform_type == 'ROT_X':
                        set_roll_axis('ROT_Z')
                    elif target.transform_type == 'ROT_Z':
                        set_roll_axis('ROT_X', invert=True)

                elif bone_roll_info.roll_type == BoneRollType.ROLL_180:
                    # +180: X>-X, Z>-Z
                    if target.transform_type == 'ROT_X':
                        set_roll_axis('ROT_X', invert=True)
                    elif target.transform_type == 'ROT_Z':
                        set_roll_axis('ROT_Z', invert=True)

                elif bone_roll_info.roll_type == BoneRollType.ROLL_270:
                    # +270: X>-Z, Z>+X
                    if target.transform_type == 'ROT_X':
                        set_roll_axis('ROT_Z', invert=True)
                    elif target.transform_type == 'ROT_Z':
                        set_roll_axis('ROT_X')

                    # if ((BoneAxisRollType.X in bone_axis_type and target.transform_type == 'ROT_X')
                    #  or (BoneAxisRollType.Y in bone_axis_type and target.transform_type == 'ROT_Y')
                    #  or (BoneAxisRollType.Z in bone_axis_type and target.transform_type == 'ROT_Z')):
                    #     if BoneAxisRollType.TO_X in bone_axis_type:
                    #         target.transform_type = 'ROT_X'
                    #     elif BoneAxisRollType.TO_Y in bone_axis_type:
                    #         target.transform_type = 'ROT_Y'
                    #     elif BoneAxisRollType.TO_Z in bone_axis_type:
                    #         target.transform_type = 'ROT_Z'

                    # if BoneAxisRollType.INVERT in bone_axis_type:
                    #     driver.expression = driver.expression.replace(variable.name, f'(-{variable.name})')


def fix_arp_bones(arp_armature_object: bpy.types.Object, daz_armature_object: bpy.types.Object, report: Optional[ReportFunctionType] = None):
    arp_armature: bpy.types.Armature = arp_armature_object.data
    arp_bones = arp_armature.edit_bones
    daz_armature: bpy.types.Armature = daz_armature_object.data
    daz_bones = daz_armature.edit_bones

    arp_bones['hand.l'].use_inherit_rotation = True
    arp_bones['hand.r'].use_inherit_rotation = True

def copy_daz_bones(arp_armature_object: bpy.types.Object, daz_armature_object: bpy.types.Object, report: Optional[ReportFunctionType] = None):
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
        new_arp_bone.align_orientation(daz_bone)
        # new_arp_bone.align_roll(daz_bone.z_axis)
        new_arp_bone.use_deform = daz_bone.use_deform
        new_arp_bone.use_connect = daz_bone.use_connect
        new_arp_bone.layers = [i in {24} for i in range(32)]

        for daz_child_bone in daz_bone.children:
            duplicate_bones_recursively(daz_child_bone, new_arp_bone)

    for daz_bone, arp_bone in copy_root_bones.items():
        duplicate_bones_recursively(daz_bone, arp_bone)


def copy_daz_constraints(arp_armature_object: bpy.types.Object, daz_armature_object: bpy.types.Object, report: Optional[ReportFunctionType] = None):
    arp_bones = arp_armature_object.pose.bones
    daz_bones = daz_armature_object.pose.bones

    for daz_bone in daz_bones:
        arp_bone: bpy.types.PoseBone
        if daz_bone.name in DAZ_TO_ARP_VERTEXGROUPS:
            arp_bone = arp_bones.get(DAZ_TO_ARP_VERTEXGROUPS[daz_bone.name])
        elif daz_bone.name in arp_bones:
            arp_bone = arp_bones[daz_bone.name]
        else:
            continue

        for daz_constraint in daz_bone.constraints:
            if daz_constraint.type == 'LIMIT_ROTATION':
                dc: bpy.types.LimitRotationConstraint = daz_constraint
                ac: bpy.types.LimitRotationConstraint = arp_bone.constraints.new(type='LIMIT_ROTATION')
                ac.name = dc.name
                ac.use_limit_x, ac.min_x, ac.max_x = dc.use_limit_x, dc.min_x, dc.max_x
                ac.use_limit_y, ac.min_y, ac.max_y = dc.use_limit_y, dc.min_y, dc.max_y
                ac.use_limit_z, ac.min_z, ac.max_z = dc.use_limit_z, dc.min_z, dc.max_z
                ac.euler_order = dc.euler_order
                ac.use_transform_limit = dc.use_transform_limit
                ac.owner_space = dc.owner_space


class DAZ2ARP_MT_object_menu(bpy.types.Menu):
    bl_label = 'Daz to AutoRig Pro'

    def draw(self, _context):
        self.layout.operator(D2A_OT_add_rig.bl_idname, text=D2A_OT_add_rig.bl_label)
        self.layout.operator(Daz2arp_vertex_group_remap.bl_idname, text=Daz2arp_vertex_group_remap.bl_label)
        self.layout.operator(Daz2arp_bone_snap.bl_idname, text=Daz2arp_bone_snap.bl_label)

    def menu_func(self, _context):
        self.layout.menu(DAZ2ARP_MT_object_menu.__name__, text=DAZ2ARP_MT_object_menu.bl_label)


def register():
    """Register and add to the "object" menu (required to also use F3 search "Simple Object Operator" for quick access)"""
    load_handler(None)
    bpy.app.handlers.load_post.append(load_handler)
    bpy.utils.register_class(Daz2arp_vertex_group_remap)
    bpy.utils.register_class(Daz2arp_bone_snap)
    bpy.utils.register_class(DAZ2ARP_MT_object_menu)
    bpy.utils.register_class(D2A_OT_add_rig)
    bpy.types.VIEW3D_MT_object.append(DAZ2ARP_MT_object_menu.menu_func)


def unregister():
    bpy.types.VIEW3D_MT_object.remove(DAZ2ARP_MT_object_menu.menu_func)
    bpy.utils.unregister_class(D2A_OT_add_rig)
    bpy.utils.unregister_class(DAZ2ARP_MT_object_menu)
    bpy.utils.unregister_class(Daz2arp_bone_snap)
    bpy.utils.unregister_class(Daz2arp_vertex_group_remap)
    bpy.app.handlers.load_post.remove(load_handler)


if __name__ == "__main__":
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

    # "lEar": "c_ear_01.l",
    # "rEar": "c_ear_01.r",
    # "lPectoral": "c_breast_01.l",
    # "rPectoral": "c_breast_01.r",
}


class BoneRollType(Enum):
    ROLL_0 = 0
    ROLL_90 = 1
    ROLL_180 = 2
    ROLL_270 = 4
    ROLL_DIFFERENCE = 8


@dataclass
class BoneRollInfo:
    roll_type: BoneRollType
    override_bone_name: str = None
    difference_bone_name: str = None
    difference_invert: bool = False


ARP_REF_BONE_ROLL_INFOS: Dict[str, BoneRollInfo] = {
    'root.x': BoneRollInfo(BoneRollType.ROLL_0, 'c_root.x'),
    'spine_01.x': BoneRollInfo(BoneRollType.ROLL_0, 'c_spine_01.x'),
    'spine_02.x': BoneRollInfo(BoneRollType.ROLL_0, 'c_spine_02.x'),
    'spine_03.x': BoneRollInfo(BoneRollType.ROLL_0, 'c_spine_03.x'),

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
    'forearm_stretch.l':  BoneRollInfo(BoneRollType.ROLL_DIFFERENCE, difference_bone_name='arm_stretch.l', difference_invert=False),
    'forearm_stretch.r':  BoneRollInfo(BoneRollType.ROLL_DIFFERENCE, difference_bone_name='arm_stretch.r', difference_invert=True),
    'hand.l': BoneRollInfo(BoneRollType.ROLL_0),
    'hand.r': BoneRollInfo(BoneRollType.ROLL_180),

    'c_subneck_1.x': BoneRollInfo(BoneRollType.ROLL_0),
    'neck.x': BoneRollInfo(BoneRollType.ROLL_0, 'c_neck.x'),
    'head.x': BoneRollInfo(BoneRollType.ROLL_0, 'c_head.x'),
}


class BoneSnapType(Flag):
    HEAD = 1
    TAIL = 2
    DISCONNECTED = 4
    FLIPPED = 8
    FOOT_PROXIMAL = 16
    SHIN = 32
    ANKLE = 64

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


ARP_REF_TO_DAZ_BONE_SNAP_INFOS: List[BoneSnapInfo] = reversed([
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
    BoneSnapInfo(BoneSnapType.HEAD, 'breast_01_ref.l', 'lPectoral'),
])
