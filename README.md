# daz2arp
This is helper Blender addon to rename/mix vertex group from Daz3D to AutoRig Pro.
It uses definition in accompanied json file.
This will transfer ONLY body parts, no facial, as I use FaceIt to generate facial rig after this.

Usage
1. Import Daz3d model via Daz To Blender addon
2. Add new human armature from AutoRig Pro addon / Do not add secondary controllers
3. Hide body mesh / Turn on vertex snapping
4. ARP->Edit Reference Bones / manually snap each bones to the coresponding Daz ones.
5. for spine, adjust limb options to have 4 spine bones
6. for feet, limb options -> add foot fingers
7. 'Match to Rig' when done.
8. Make sure the mesh is selected
9. A new menu item call 'Daz to ARP' is in Object menu - one click to rename vertex groups
10. Optional : there are excess vertex groups that's currently unlocked, you can delete all unlocked group to clear them.
11. Change Armature modifier -> object from Daz to Autorig Pro one
