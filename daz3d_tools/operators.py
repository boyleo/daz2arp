# -*- coding: utf-8 -*-
# Copyright 2023 UuuNyaa <UuuNyaa@gmail.com>, boyleo https://github.com/boyleo/daz2arp
# This file is part of Daz3D Tools.

from typing import List, Set, Tuple

import bmesh
import bpy
import mathutils
from mathutils import Vector

from daz3d_tools.functions import (copy_daz_bones, copy_daz_constraints,
                                   find_user_layer_collection, fix_arp_bones,
                                   fix_daz_corrective_shape_keys,
                                   remap_daz_corrective_shape_keys,
                                   remap_daz_vertex_groups,
                                   snap_arp_ref_bones_to_daz_bones,
                                   try_import_module)


class D2A_OT_convert_daz_to_arp(bpy.types.Operator):
    bl_idname = 'daz3d_tools.convert_daz_to_arp'
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
        snap_arp_ref_bones_to_daz_bones(arp_armature_object, daz_armature_object, self.report)

        bpy.ops.arp.match_to_rig()

        arp_armature_object = next(o for o in context.selected_objects if o.type == 'ARMATURE' and o != daz_armature_object)

        bpy.ops.object.mode_set(mode='EDIT')
        if self.copy_daz_remaining_bones:
            copy_daz_bones(arp_armature_object, daz_armature_object, self.report)
        fix_arp_bones(arp_armature_object)

        bpy.ops.object.mode_set(mode='POSE')
        copy_daz_constraints(arp_armature_object, daz_armature_object, self.report)

        bpy.ops.object.mode_set(mode='OBJECT')
        fix_daz_corrective_shape_keys(arp_armature_object, daz_armature_object, self.report)

        if self.remap_daz_corrective_shape_keys:
            remap_daz_corrective_shape_keys(arp_armature_object, daz_armature_object, self.report)

        arp_layer_collection = find_user_layer_collection(arp_armature_object)

        if self.remap_daz_vertex_groups:
            daz_mesh_object: bpy.types.Object
            for daz_mesh_object in daz_armature_object.children:
                if daz_mesh_object.type != 'MESH':
                    continue

                remap_daz_vertex_groups(daz_mesh_object, self.report)
                daz_mesh_object.parent = arp_armature_object
                daz_layer_collection = find_user_layer_collection(daz_mesh_object)
                arp_layer_collection.collection.objects.link(daz_mesh_object)
                daz_layer_collection.collection.objects.unlink(daz_mesh_object)

                for modifier in daz_mesh_object.modifiers:
                    if modifier.type != 'ARMATURE':
                        continue
                    modifier.object = arp_armature_object

        return {'FINISHED'}

    def _add_arp_rig(self, context: bpy.types.Context, add_breast_bones: bool) -> bpy.types.Object:
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
        select_bone('thigh_ref.r')
        arp.set_toes(True, True, True, True, True)

        # add ears
        arp.set_ears(1)

        # add breast bones
        if add_breast_bones:
            arp.set_breast(True)

        return armature_object

    @staticmethod
    def draw_menu(this, _):
        this.layout.operator(D2A_OT_convert_daz_to_arp.bl_idname, text=D2A_OT_convert_daz_to_arp.bl_label)

    @staticmethod
    def register():
        """Register and add to the "object" menu (required to also use F3 search "Simple Object Operator" for quick access)"""
        bpy.types.VIEW3D_MT_object.append(D2A_OT_convert_daz_to_arp.draw_menu)

    @staticmethod
    def unregister():
        bpy.types.VIEW3D_MT_object.remove(D2A_OT_convert_daz_to_arp.draw_menu)


class SelectNearVerticesOperator(bpy.types.Operator):
    bl_idname = 'daz3d_tools.select_near_vertices'
    bl_label = 'Select Near Vertices'
    bl_options = {'REGISTER', 'UNDO'}

    distance_threshold: bpy.props.FloatProperty(name='Distance Threshold', default=0.0, min=0.0, subtype='DISTANCE')

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        if context.mode != 'EDIT_MESH':
            return False
        return len([o for o in context.selected_objects if o.type == 'MESH']) > 0

    def execute(self, context: bpy.types.Context) -> Set[str]:
        target_mesh_objects: List[bpy.types.Object] = [o for o in context.selected_objects if o.type == 'MESH' and not o.hide]

        mesh_bmeshes: List[Tuple[bpy.types.Mesh, bmesh.types.BMesh]] = [(m.data, bmesh.from_edit_mesh(m.data)) for m in target_mesh_objects]

        vertex_index = mathutils.kdtree.KDTree(sum((len(b.verts) for _, b in mesh_bmeshes)))

        for _mesh, bm in mesh_bmeshes:
            vertex: bmesh.types.BMVert
            for vertex in bm.verts:
                if not vertex.select:
                    continue

                vertex_index.insert(vertex.co, vertex.index)

        vertex_index.balance()

        distance_threshold = self.distance_threshold

        for mesh, bm in mesh_bmeshes:
            vertex: bmesh.types.BMVert
            for vertex in bm.verts:
                if vertex.select:
                    continue

                _co, _index, distance = vertex_index.find(vertex.co)
                if distance < distance_threshold:
                    vertex.select_set(True)

            bm.select_mode |= {'VERT'}
            bm.select_flush_mode()
            bmesh.update_edit_mesh(mesh)

        return {'FINISHED'}

    @staticmethod
    def draw_menu(this, _):
        this.layout.operator(SelectNearVerticesOperator.bl_idname, text='Select Near Vertices')

    @staticmethod
    def register():
        bpy.types.VIEW3D_MT_select_edit_mesh.append(SelectNearVerticesOperator.draw_menu)

    @staticmethod
    def unregister():
        bpy.types.VIEW3D_MT_select_edit_mesh.remove(SelectNearVerticesOperator.draw_menu)


class SnapVerticesToActiveMeshOperator(bpy.types.Operator):
    bl_idname = 'daz3d_tools.snap_vertices_to_active_mesh'
    bl_label = 'Snap Vertices to Active Mesh'
    bl_options = {'REGISTER', 'UNDO'}

    distance_threshold: bpy.props.FloatProperty(name='Distance Threshold', default=0.001, min=0.0, subtype='DISTANCE')
    snap_only_selected_vertices: bpy.props.BoolProperty(name='Snap only selected vertices', default=False)

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        if context.mode != 'EDIT_MESH':
            return False

        if context.active_object is None or context.active_object.type != 'MESH':
            return False

        return len([o for o in context.objects_in_mode_unique_data if o.type == 'MESH']) > 0

    def execute(self, context: bpy.types.Context) -> Set[str]:
        snap_mesh_object: bpy.types.Object = context.active_object
        edit_mesh_objects: List[bpy.types.Object] = [o for o in context.objects_in_mode_unique_data if o.type == 'MESH' and o != snap_mesh_object and not o.hide]

        snap_mesh_object_matrix_world = snap_mesh_object.matrix_world
        snap_mesh: bpy.types.Mesh = snap_mesh_object.data
        snap_bmesh: bmesh.types.BMesh = bmesh.from_edit_mesh(snap_mesh)

        vertex_index = mathutils.kdtree.KDTree(len(snap_bmesh.verts))

        snap_only_selected_vertices = self.snap_only_selected_vertices

        vertex: bmesh.types.BMVert
        for vertex in snap_bmesh.verts:
            if snap_only_selected_vertices and not vertex.select:
                continue
            vertex_index.insert(snap_mesh_object_matrix_world @ vertex.co, vertex.index)
        vertex_index.balance()

        edit_bmeshes: List[bmesh.types.BMesh] = [bmesh.from_edit_mesh(m.data) for m in edit_mesh_objects]

        distance_threshold = self.distance_threshold

        candidate_vertices: List[Tuple[Tuple[Vector, int, float], bmesh.types.BMVert]] = []
        for mesh_object, bm in zip(edit_mesh_objects, edit_bmeshes):
            mesh_object_matrix_world = mesh_object.matrix_world
            mesh_object_matrix_world_invert = mesh_object.matrix_world.inverted_safe()
            vertex: bmesh.types.BMVert
            for vertex in bm.verts:
                if not vertex.select:
                    continue
                candidate_vertices.extend((c, vertex, mesh_object_matrix_world_invert) for c in vertex_index.find_range(mesh_object_matrix_world @ vertex.co, distance_threshold))

        vertex_index = None  # allow GC

        # sort by distance
        candidate_vertices.sort(key=lambda e: e[0][2])

        consumed_indices: Set[int] = set()
        for (co, index, _distance), vertex, mesh_object_matrix_world_invert in candidate_vertices:
            if index in consumed_indices:
                continue
            vertex.co = mesh_object_matrix_world_invert @ co
            vertex.select_set(False)
            consumed_indices.add(index)

        for mesh_object, bm in zip(edit_mesh_objects, edit_bmeshes):
            bm.select_mode |= {'VERT'}
            bm.select_flush_mode()
            bmesh.update_edit_mesh(mesh_object.data)

        return {'FINISHED'}

    @staticmethod
    def draw_menu(this, _):
        this.layout.operator(SnapVerticesToActiveMeshOperator.bl_idname, text='Snap to Active Mesh')

    @staticmethod
    def register():
        bpy.types.VIEW3D_MT_edit_mesh_vertices.append(SnapVerticesToActiveMeshOperator.draw_menu)

    @staticmethod
    def unregister():
        bpy.types.VIEW3D_MT_edit_mesh_vertices.remove(SnapVerticesToActiveMeshOperator.draw_menu)
