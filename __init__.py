# Rename/Remix vertex groups from Daz 3D model to AutoRig Pro
# --- limitations ---
# - no secondary controllers
# - edit limb option on spine for 4 spine bones to be compatible with UE4 mannequin
# - edit limb options on both legs to have toe fingers
# - add breasts / ears (1 bone)

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

import bpy
import os
import addon_utils
from bpy.types import Operator
import json

def combine_vertex_group(v1, v2):
    bpy.ops.object.modifier_add(type='VERTEX_WEIGHT_MIX')
    bpy.ops.object.modifier_move_to_index(modifier="VertexWeightMix", index=0)
    bpy.context.object.modifiers[0].name = v1
    bpy.context.object.modifiers[0].vertex_group_a = v1
    bpy.context.object.modifiers[0].vertex_group_b = v2
    bpy.context.object.modifiers[0].mix_mode = 'ADD'
    bpy.context.object.modifiers[0].mix_set = 'ALL'
    bpy.ops.object.modifier_apply(modifier=v1)


class Daz2arp_vertex_group_remap(bpy.types.Operator):
    """Remap Daz vertex group to AutoRig Pro"""
    bl_idname = "mesh.daz2arp_vertex_group_remap"
    bl_label = "Daz to ARP"
                
    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def execute(self, context):
        # load remap definition from json file
        file_name = "daz_to_arp_vertexgroups.json"
        
        for mod in addon_utils.modules():
            if mod.bl_info['name'] == "Daz2ARP":
                filepath = mod.__file__
            
        absPath = os.path.dirname(filepath)+"\\"+file_name
        
        with open(absPath) as f:
            vg = json.load(f)

        newName = "Blah"

        # remap each vertex group
        for m in bpy.context.selected_objects:
            if m.type == 'MESH':
                for i in vg:
                    newName = vg[i]
                    try:
                        m.vertex_groups[i].name = newName
                        m.vertex_groups[newName].lock_weight = True
                        txt = "changed vertex group "+i+" to "+newName
                        self.report({'INFO'}, txt)
                    except:
                        self.report({'INFO'}, "vertext group "+i+" not found in this object")
        
        # some bones are unavailable in ARP
        # so merge them with adjacent bones
        try:
            combine_vertex_group("foot.l", "lMetatarsals")
        except:
            self.report({'INFO'}, "lMetatarsals not merged")
            bpy.ops.object.modifier_remove(modifier="foot.l")
            
        try:
            combine_vertex_group("foot.r", "rMetatarsals")
        except:
            self.report({'INFO'}, "rMetatarsals not merged")
            bpy.ops.object.modifier_remove(modifier="foot.r")
            
        try:
            combine_vertex_group("spine_03.x", "chestUpper")
        except:
            self.report({'INFO'}, "chestUpper not merged")
            bpy.ops.object.modifier_remove(modifier="spine_03.x")
            
        return {'FINISHED'}

def menu_func(self, context):
    self.layout.operator(Daz2arp_vertex_group_remap.bl_idname, text=Daz2arp_vertex_group_remap.bl_label)

# Register and add to the "object" menu (required to also use F3 search "Simple Object Operator" for quick access)
def register():
    bpy.utils.register_class(Daz2arp_vertex_group_remap)
    bpy.types.VIEW3D_MT_object.append(menu_func)


def unregister():
    bpy.utils.unregister_class(Daz2arp_vertex_group_remap)
    bpy.types.VIEW3D_MT_object.remove(menu_func)


if __name__ == "__main__":
    register()

    # test call
    #bpy.ops.object.simple_operator()
