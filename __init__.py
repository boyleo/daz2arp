# Rename/Remix vertex groups from Daz 3D model to AutoRig Pro
# --- limitations ---
# - no secondary controllers
# - edit limb option on spine for 4 spine bones to be compatible with UE4 mannequin
# - edit limb options on both legs to have toe fingers
# - add breasts / ears (1 bone)

import logging
import traceback

import bpy

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
            self.combine_vertex_group(obj, "spine_03.x", "chestUpper")

        return {'FINISHED'}


def menu_func(self, _context):
    self.layout.operator(Daz2arp_vertex_group_remap.bl_idname, text=Daz2arp_vertex_group_remap.bl_label)


def register():
    """Register and add to the "object" menu (required to also use F3 search "Simple Object Operator" for quick access)"""
    bpy.utils.register_class(Daz2arp_vertex_group_remap)
    bpy.types.VIEW3D_MT_object.append(menu_func)


def unregister():
    bpy.utils.unregister_class(Daz2arp_vertex_group_remap)
    bpy.types.VIEW3D_MT_object.remove(menu_func)


if __name__ == "__main__":
    register()


DAZ_TO_ARP_VERTEXGROUPS = {
    "pelvis": "root.x",
    "lThighBend": "thigh_twist.l",
    "lThighTwist": "thigh_stretch.l",
    "lShin": "leg_stretch.l",
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
    "rPectoral": "c_breast_01.r"
}
