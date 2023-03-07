bl_info = {
    "name": "Wiggle 2",
    "author": "Steve Miller",
    "version": (2, 0, 0),
    "blender": (3, 00, 0),
    "location": "3d Viewport > Animation Panel",
    "description": "Simulate spring-like physics on Bone transforms",
    "warning": "",
    "wiki_url": "",
    "category": "Animation",
}

### TO DO #####

# wiggle bone position
# Basic object wiggle?
# [KINDA?] Implement a constant physics step
# [DONE] Bounciness improve
# [DONE] friction improve
# [DONE] Length stiffness 1 should have no give
# [DONE] indirect parents

# bugs:
# [DONE] crash when deleting a collider still referened by bone
# [DONE] keyframe poses don't reset properly

import bpy, math
from mathutils import Vector, Matrix, Euler, Quaternion, geometry
from bpy.app.handlers import persistent

reset = False

#return m2 in m1 space
def relative_matrix(m1,m2):
    return (m2.inverted() @ m1).inverted()

def flatten(mat):
    dim = len(mat)
    return [mat[j][i] for i in range(dim) 
                      for j in range(dim)]
                      
def get_parent(b):
    p = b.parent
    if not p: return None
    par = p if p.wiggle_enable else get_parent(p)
    return par

def get_b(item):
    ob = bpy.context.scene.objects.get(item.object)
    if not ob:
        build_list()
        return None
    b = ob.pose.bones.get(item.bone)
    if not b:
        build_list()
        return None
    return b

def get_p(item):
    if item.parent == -1: return None, None
    p_item = bpy.context.scene.wiggle.list[item.parent]
    return p_item, get_b(p_item)
                     
def build_list():
    list = bpy.context.scene.wiggle.list
    list.clear()
    if not bpy.context.scene.wiggle_enable: return

    def set_p(item):
        b=get_b(item)
        p = get_parent(b)
        if p:
            for idx, i2 in enumerate(list):
                if (i2.object == p.id_data.name) and (i2.bone == p.name):
                    item.parent = idx

    for ob in bpy.context.scene.objects:
        if ob.type != 'ARMATURE': continue
        if not ob.wiggle_enable: continue
                        
        for b in ob.pose.bones:
            if b.wiggle_enable_head:
                item = list.add()
                item.object = ob.name
                item.bone = b.name
                item.tail = False
                set_p(item)
            if b.wiggle_enable:
                item = list.add()
                item.object = ob.name
                item.bone = b.name
                set_p(item)
    bpy.ops.wiggle.reset()
        
def update_prop(self,context,prop): 
    if type(self) == bpy.types.PoseBone: 
        for b in context.selected_pose_bones:
            b[prop] = self[prop]
    if prop == 'wiggle_enable':
        build_list()

def length_world(b):
    return (b.id_data.matrix_world @ b.head - b.id_data.matrix_world @ b.tail).length

def collider_poll(self, object):
    return object.type == 'MESH'

def collide(b,dg):
    dt = bpy.context.scene.wiggle.dt
    
    pos = b.wiggle.position
    vel = b.wiggle.velocity
    cp = b.wiggle.collision_point
    co = b.wiggle.collision_ob
    radius = b.wiggle_radius
    sticky = b.wiggle_sticky
    bounce = b.wiggle_bounce
    friction = b.wiggle_friction
    
    colliders = []
    if b.wiggle_collider_type == 'Object' and b.wiggle_collider:
        if b.wiggle_collider.name in bpy.context.scene.objects:
            colliders = [b.wiggle_collider]
        else: b.wiggle_collider = None
    if b.wiggle_collider_type == 'Collection' and b.wiggle_collider_collection:
        if b.wiggle_collider_collection.name in bpy.context.scene.collection.children:
            colliders = [ob for ob in b.wiggle_collider_collection.objects if ob.type == 'MESH']
        else: b.wiggle_collider_collection = None
    col = False
    for collider in colliders:
        cmw = collider.matrix_world
        p = collider.closest_point_on_mesh(cmw.inverted() @ pos, depsgraph=dg)
        n = (cmw.to_quaternion().to_matrix().to_4x4() @ p[2]).normalized()
        i = cmw @ p[1]
        v = i-pos
        
        if (n.dot(v.normalized()) > 0.01) or (v.length < radius) or (co and (v.length < (radius+sticky))):
            if n.dot(v.normalized()) > 0: #vec is below
                nv = v.normalized()
            else: #normal is opposite dir to vec
                nv = -v.normalized()
            pos = i + nv*radius
            
            if co:
                collision_point = co.matrix_world @ cp
                pos = pos.lerp(collision_point, friction) # min(1,friction*60*dt))
            col = True
            co = collider
            cp = relative_matrix(cmw, Matrix.Translation(pos)).translation
            b.wiggle.collision_normal = nv
    if not col:
        co = None
        cp = Vector((0,0,0))
        
    b.wiggle.position = pos
    b.wiggle.collision_point = cp
    b.wiggle.collision_ob = co  

def update_matrix(item):
    b = get_b(item)
    p_item,p = get_p(item)
    if p:
        mat = p_item.matrix @ relative_matrix(p.matrix, b.matrix)
        if b.bone.inherit_scale == 'FULL':
            m2 = mat
        else:
            diff = relative_matrix(p.matrix, b.matrix)
            lo = Matrix.Translation((p_item.matrix @ diff).translation)
            ro = p_item.matrix.to_quaternion().to_matrix().to_4x4() @ diff.to_quaternion().to_matrix().to_4x4()
            sc = Matrix.LocRotScale(None,None,(b.id_data.matrix_world @ b.matrix).decompose()[2])
            m2 = lo @ ro @ sc
            
    else:
        mat = b.id_data.matrix_world @ b.matrix
        m2 = mat
    
    vec = relative_matrix(m2, Matrix.Translation(item.position)).translation
    rxz = vec.to_track_quat('Y','Z')
    rot = rxz.to_matrix().to_4x4()
    
    if not p:
        sy = (b.id_data.matrix_world @ b.matrix.translation - item.position).length/length_world(b)
    else:
        if b.bone.inherit_scale == 'FULL':
            l0=relative_matrix(mat, Matrix.Translation(mat @ Vector((0,b.length,0)))).translation.length
            l1=relative_matrix(mat, Matrix.Translation(item.position)).translation.length
            sy = l1/l0
        else:
            sy = (p_item.matrix @ relative_matrix(p.matrix, b.matrix).translation - item.position).length/length_world(b)
    scale = Matrix.Scale(sy,4,Vector((0,1,0)))
    
    b.matrix = b.matrix @ rot @ scale
    item.matrix = flatten(m2 @ rot @ scale)
    
def pin(b):
    for c in b.constraints:
        if c.type == 'DAMPED_TRACK' and c.target and not c.mute:
            b.wiggle.position = b.wiggle.position*(1-c.influence) + c.target.location*c.influence
            break

#can include gravity, wind, etc    
def move(item,dg):
    dt = bpy.context.scene.wiggle.dt
    if dt:
        b = bpy.context.scene.objects[item.object].pose.bones[item.bone]
        damp = max(min(1-b.wiggle_damp*dt, 1),0) 
        Fg = bpy.context.scene.gravity * b.wiggle_gravity
        item.velocity = item.velocity*damp
        item.position += item.velocity + Fg*dt*dt
#        pin(b)
#        collide(b,dg)
        update_matrix(item)

def constrain(item,i,dg):
    dt = bpy.context.scene.wiggle.dt
    
    def spring(item, b, mat):
        target = mat @ Vector((0,b.bone.length,0))
        s = target - item.position
        Fs = b.wiggle_stiff * s / bpy.context.scene.wiggle.iterations
        return Fs*dt*dt
    
    b = get_b(item)

    if dt:
        p_item,p = get_p(item)
        if p:
            if i:
                if b.wiggle_mass == p.wiggle_mass:
                    fac=0.5
                else:
                    fac=b.wiggle_mass/(p.wiggle_mass + b.wiggle_mass)
            else:
                fac = p.wiggle_stretch
            
            #spring
            mat = p_item.matrix @ relative_matrix(p.matrix, b.matrix)
            mat = Matrix.LocRotScale(mat.decompose()[0], mat.decompose()[1],b.matrix.decompose()[2])
            s = spring(item,b,mat)
            if p == b.parent and b.bone.use_connect:
                p_item.position -= s*fac
                item.position += s*(1-fac)
            else:
                item.position += s*fac
            
            #stretch
            target = mat.translation + (item.position - mat.translation).normalized()*length_world(b)
            s = (target - item.position)*(1-b.wiggle_stretch)
            
            if p == b.parent and b.bone.use_connect:
                p_item.position -= s*fac
                item.position += s*(1-fac)
            else:
                item.position += s*fac
#            pin(p)
#            collide(p,dg)

        else:#no parent
            #spring
            mat = b.id_data.matrix_world @ b.matrix
            s=spring(item,b,mat)
            item.position += s
            
            #stretch
            target = item.matrix.translation + (item.position - item.matrix.translation).normalized()*length_world(b)
            s = (target - item.position)*(1-b.wiggle_stretch)
            item.position += s
#        pin(b)
#        collide(b,dg)
    update_matrix(item)
 
        
@persistent
def wiggle_pre(scene):
    if not scene.wiggle_enable: return
    for item in scene.wiggle.list:
        b = get_b(item)
        b.location = Vector((0,0,0))
        b.rotation_quaternion = Quaternion((1,0,0,0))
        b.rotation_euler = Vector((0,0,0))
        b.scale = Vector((1,1,1))
    bpy.context.view_layer.update()

@persistent                
def wiggle_post(scene,dg):
    global reset
    if reset: return

    if not scene.wiggle_enable: return

    lastframe = scene.wiggle.lastframe
    if (scene.frame_current == scene.frame_start) and (scene.wiggle.loop == False) and (scene.wiggle.is_preroll == False):
        bpy.ops.wiggle.reset()
        return
    if scene.frame_current >= lastframe:
        frames_elapsed = scene.frame_current - lastframe
    else:
        e1 = (scene.frame_end - lastframe) + (scene.frame_current - scene.frame_start) + 1
        e2 = lastframe - scene.frame_current
        frames_elapsed = min(e1,e2)
    if frames_elapsed > 4: frames_elapsed = 1 #handle large jumps?
    scene.wiggle.dt = 1/scene.render.fps * frames_elapsed
    scene.wiggle.lastframe = scene.frame_current
    
    for item in scene.wiggle.list:
        item.collision_normal = Vector((0,0,0))
        move(item,dg)
    for i in range(scene.wiggle.iterations):
        for item in scene.wiggle.list:
            constrain(item, scene.wiggle.iterations-1-i,dg)
    if frames_elapsed:
        for item in scene.wiggle.list:
            item.velocity = (item.position - item.position_last)/frames_elapsed
            if item.collision_normal.length:
                item.velocity = item.velocity.reflect(item.collision_normal)*item.object.pose.bones[item.bone].wiggle_bounce
            item.position_last = item.position
            
class WiggleCopy(bpy.types.Operator):
    """Copy active wiggle settings to selected bones"""
    bl_idname = "wiggle.copy"
    bl_label = "Copy Settings to Selected"
    
    @classmethod
    def poll(cls,context):
        return context.mode in ['POSE'] and context.active_pose_bone and (len(context.selected_pose_bones)>1)
    
    def execute(self,context):
        b = context.active_pose_bone
        b.wiggle_enable = b.wiggle_enable
        b.wiggle_enable_head = b.wiggle_enable_head
        b.wiggle_mass = b.wiggle_mass
        b.wiggle_stiff = b.wiggle_stiff
        b.wiggle_stretch = b.wiggle_stretch
        b.wiggle_damp = b.wiggle_damp
        b.wiggle_gravity = b.wiggle_gravity
        b.wiggle_collider_type = b.wiggle_collider_type
        b.wiggle_collider = b.wiggle_collider
        b.wiggle_collider_collection = b.wiggle_collider_collection
        b.wiggle_radius = b.wiggle_radius
        b.wiggle_friction = b.wiggle_friction
        b.wiggle_bounce = b.wiggle_bounce
        b.wiggle_sticky = b.wiggle_sticky
        return {'FINISHED'}

class WiggleReset(bpy.types.Operator):
    """Reset wiggle physics to rest state"""
    bl_idname = "wiggle.reset"
    bl_label = "Reset Physics"
    
    @classmethod
    def poll(cls,context):
        return context.scene.wiggle_enable and context.mode in ['OBJECT', 'POSE']
    
    def execute(self,context):
        global reset
        reset = True
        context.scene.frame_set(context.scene.frame_current)
        reset = False
        for item in context.scene.wiggle.list:
            b = get_b(item)
            item.position = item.position_last = (b.id_data.matrix_world @ Matrix.Translation(b.tail)).translation
            item.velocity = Vector((0,0,0))
            item.matrix = flatten(b.id_data.matrix_world @ b.matrix)
        context.scene.wiggle.lastframe = context.scene.frame_current
        return {'FINISHED'}
    
class WiggleSelect(bpy.types.Operator):
    """Select wiggle bones on selected objects in pose mode"""
    bl_idname = "wiggle.select"
    bl_label = "Select Enabled"
    
    @classmethod
    def poll(cls,context):
        return context.mode in ['POSE']
    
    def execute(self,context):
        bpy.ops.pose.select_all(action='DESELECT')
        for ob in context.selected_objects:
            if ob.wiggle_enable and ob.mode == 'POSE':
                for wb in ob.wiggle.list:
                    b = ob.pose.bones[wb.name]
                    b.bone.select = True
        return {'FINISHED'}  
    
class WiggleBake(bpy.types.Operator):
    """Bake this object's wiggle bones to keyframes"""
    bl_idname = "wiggle.bake"
    bl_label = "Bake Wiggle"
    
    @classmethod
    def poll(cls,context):
        return context.object
    
    def execute(self,context):
        #preroll
        duration = context.scene.frame_end - context.scene.frame_start + 1
        preroll = context.scene.wiggle.preroll
        context.scene.wiggle.is_preroll = False
        bpy.ops.wiggle.select()
        bpy.ops.wiggle.reset()
        while preroll >= 0:
            if context.scene.wiggle.loop:
                frame = context.scene.frame_end - (preroll%duration)
                context.scene.frame_set(frame)
            else:
                context.scene.frame_set(context.scene.frame_start)
            context.scene.wiggle.is_preroll = True
            preroll -= 1
        bpy.ops.nla.bake(frame_start = context.scene.frame_start,
                        frame_end = context.scene.frame_end,
                        only_selected = True,
                        visual_keying = True,
                        use_current_action = context.scene.wiggle.bake_overwrite,
                        bake_types={'POSE'})
        context.scene.wiggle.is_preroll = False
        context.object.wiggle_enable = False
        return {'FINISHED'}  

class WigglePanel:
    bl_category = 'Animation'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    
    @classmethod
    def poll(cls,context):
        return context.object  

class WIGGLE_PT_Settings(WigglePanel, bpy.types.Panel):
    bl_label = 'Wiggle 2'
    
    def draw(self,context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        def drawprops(layout,b,props):
            for p in props:
                layout.prop(b, p)
                
        row = layout.row()
        row.prop(context.scene, 'wiggle_enable', icon = 'SCENE_DATA',icon_only=True)
        ob = context.object
        if ob.type == 'ARMATURE':
            row.prop(ob, 'wiggle_enable', icon = 'OBJECT_DATA',icon_only=True)
        if not context.scene.wiggle_enable or context.active_object.mode != 'POSE' or not context.active_pose_bone:
            return
        b = context.active_pose_bone
        row = row.row(align=True)
        row.prop(b, 'wiggle_enable_head', icon = 'BONE_DATA',icon_only=True)
        row.prop(b, 'wiggle_enable', icon = 'BONE_DATA',icon_only=True)
        if not b.wiggle_enable:
            return
        col = layout.column(align=True)
        drawprops(col,b,['wiggle_mass','wiggle_stiff','wiggle_stretch','wiggle_damp'])
        col = layout.column(align=True)
        drawprops(col,b,['wiggle_gravity'])
        layout.separator()
        layout.prop(b, 'wiggle_collider_type',text='Collisions')
        collision = False
        if b.wiggle_collider_type == 'Object':
            layout.prop_search(b, 'wiggle_collider', context.scene, 'objects',text=' ')
            if b.wiggle_collider: collision = True
        else:
            layout.prop_search(b, 'wiggle_collider_collection', context.scene.collection, 'children', text=' ')
            if b.wiggle_collider_collection: collision = True
        if collision:
            drawprops(layout,b,['wiggle_radius','wiggle_friction','wiggle_bounce','wiggle_sticky'])
        layout.separator()
        layout.operator('wiggle.copy')
                
class WIGGLE_PT_Utilities(WigglePanel,bpy.types.Panel):
    bl_label = 'Global Wiggle Utilities'
    bl_parent_id = 'WIGGLE_PT_Settings'
    
    def draw(self,context):
        layout = self.layout
        layout.use_property_split=True
        layout.use_property_decorate=False
        layout.prop(context.scene.wiggle, 'iterations')
        layout.prop(context.scene.wiggle, 'loop')
        layout.operator('wiggle.reset')
        if context.object.wiggle_enable and context.mode == 'POSE':
            layout.operator('wiggle.select')
                    
class WIGGLE_PT_Bake(WigglePanel,bpy.types.Panel):
    bl_label = 'Bake Wiggle'
    bl_parent_id = 'WIGGLE_PT_Utilities'
    
    @classmethod
    def poll(cls,context):
        return context.scene.wiggle_enable and context.object.wiggle_enable and context.mode == 'POSE'
    
    def draw(self,context):
        layout = self.layout
        layout.use_property_split=True
        layout.use_property_decorate=False
        layout.prop(context.scene.wiggle, 'preroll')
        layout.prop(context.scene.wiggle, 'bake_overwrite')
        layout.operator('wiggle.bake')
        
class WiggleItem(bpy.types.PropertyGroup):
    object: bpy.props.StringProperty(override={'LIBRARY_OVERRIDABLE'})
    bone: bpy.props.StringProperty(override={'LIBRARY_OVERRIDABLE'})
    tail: bpy.props.BoolProperty(default=True,override={'LIBRARY_OVERRIDABLE'})
    parent: bpy.props.IntProperty(default=-1,override={'LIBRARY_OVERRIDABLE'})
    
    matrix: bpy.props.FloatVectorProperty(size=16, subtype = 'MATRIX', override={'LIBRARY_OVERRIDABLE'})
    position: bpy.props.FloatVectorProperty(subtype='TRANSLATION', override={'LIBRARY_OVERRIDABLE'})
    position_last: bpy.props.FloatVectorProperty(subtype='TRANSLATION', override={'LIBRARY_OVERRIDABLE'})
    velocity: bpy.props.FloatVectorProperty(subtype='VELOCITY', override={'LIBRARY_OVERRIDABLE'})
    
    collision_point:bpy.props.FloatVectorProperty(subtype = 'TRANSLATION', override={'LIBRARY_OVERRIDABLE'})
    collision_ob: bpy.props.PointerProperty(type=bpy.types.Object, override={'LIBRARY_OVERRIDABLE'})
    collision_normal: bpy.props.FloatVectorProperty(subtype = 'TRANSLATION', override={'LIBRARY_OVERRIDABLE'})
    
    name: bpy.props.StringProperty(override={'LIBRARY_OVERRIDABLE'})        
    
class WiggleScene(bpy.types.PropertyGroup):
    dt: bpy.props.FloatProperty()
    lastframe: bpy.props.IntProperty()
    iterations: bpy.props.IntProperty(name='Quality', description='Increase solver iterations for better chain physics', min=1, default=1, soft_max=4, max=10)
    loop: bpy.props.BoolProperty(name='Looping', description='Physics continues as timeline loops', default=True)
    list: bpy.props.CollectionProperty(type=WiggleItem, override={'LIBRARY_OVERRIDABLE','USE_INSERTION'})
    preroll: bpy.props.IntProperty(name = 'Preroll', description='Frames to let simulation run before baking', min=0, default=0)
    is_preroll: bpy.props.BoolProperty(default=False)
    bake_overwrite: bpy.props.BoolProperty(name='Overwrite', description='Bake wiggle into current action, instead of creating a new one', default = False)

def register():
    #user variables
    bpy.types.Scene.wiggle_enable = bpy.props.BoolProperty(
        name = 'Enable Scene',
        description = 'Enable wiggle on this scene',
        default = False,
        override={'LIBRARY_OVERRIDABLE'},
        update=lambda s, c: update_prop(s, c, 'wiggle_enable')
    )
    bpy.types.Object.wiggle_enable = bpy.props.BoolProperty(
        name = 'Enable Object',
        description = 'Enable wiggle on this object',
        default = False,
        override={'LIBRARY_OVERRIDABLE'},
        update=lambda s, c: update_prop(s, c, 'wiggle_enable')
    )
    bpy.types.PoseBone.wiggle_enable = bpy.props.BoolProperty(
        name = 'Enable Bone Tail',
        description = 'Enable wiggle on this bone tail',
        default = False,
        override={'LIBRARY_OVERRIDABLE'},
        update=lambda s, c: update_prop(s, c, 'wiggle_enable')
    )
    bpy.types.PoseBone.wiggle_enable_head = bpy.props.BoolProperty(
        name = 'Enable Bone Head',
        description = 'Enable wiggle on this bone head',
        default = False,
        override={'LIBRARY_OVERRIDABLE'},
        update=lambda s, c: update_prop(s, c, 'wiggle_enable_head')
    )
    bpy.types.PoseBone.wiggle_mass = bpy.props.FloatProperty(
        name = 'Mass',
        description = 'Mass of bone (kinda not totally implemented)',
        min = 0.01,
        default = 1,
        override={'LIBRARY_OVERRIDABLE'},
        update=lambda s, c: update_prop(s, c, 'wiggle_mass')
    )
    bpy.types.PoseBone.wiggle_stiff = bpy.props.FloatProperty(
        name = 'Stiff',
        description = 'Stiffness coefficient, can be large numbers',
        min = 0,
        default = 20,
        override={'LIBRARY_OVERRIDABLE'},
        update=lambda s, c: update_prop(s, c, 'wiggle_stiff')
    )
    bpy.types.PoseBone.wiggle_stretch = bpy.props.FloatProperty(
        name = 'Stretch',
        description = 'Stretch factor, 0 to 1 range',
        min = 0,
        default = 0,
        max=1,
        override={'LIBRARY_OVERRIDABLE'},
        update=lambda s, c: update_prop(s, c, 'wiggle_stretch')
    )
    bpy.types.PoseBone.wiggle_damp = bpy.props.FloatProperty(
        name = 'Damp',
        description = 'Dampening coefficient, can be greater than 1',
        min = 0,
        default = 1,
        override={'LIBRARY_OVERRIDABLE'},
        update=lambda s, c: update_prop(s, c, 'wiggle_damp')
    )
    bpy.types.PoseBone.wiggle_gravity = bpy.props.FloatProperty(
        name = 'Gravity',
        description = 'Multiplier for scene gravity',
        default = 1,
        override={'LIBRARY_OVERRIDABLE'},
        update=lambda s, c: update_prop(s, c, 'wiggle_gravity')
    )
    bpy.types.PoseBone.wiggle_collider_type = bpy.props.EnumProperty(
        name='Collider Type',
        items=[('Object','Object','Collide with a selected mesh'),('Collection','Collection','Collide with all meshes in selected collection')],
        override={'LIBRARY_OVERRIDABLE'},
        update=lambda s, c: update_prop(s, c, 'wiggle_collider_type')
    )
    bpy.types.PoseBone.wiggle_collider = bpy.props.PointerProperty(
        name='Collider Object', 
        description='Mesh object to collide with', 
        type=bpy.types.Object, 
        poll = collider_poll, 
        override={'LIBRARY_OVERRIDABLE'}, 
        update=lambda s, c: update_prop(s, c, 'wiggle_collider')
    )
    bpy.types.PoseBone.wiggle_collider_collection = bpy.props.PointerProperty(
        name = 'Collider Collection', 
        description='Collection to collide with', 
        type=bpy.types.Collection, 
        override={'LIBRARY_OVERRIDABLE'}, 
        update=lambda s, c: update_prop(s, c, 'wiggle_collider_collection')
    )
    
    bpy.types.PoseBone.wiggle_radius = bpy.props.FloatProperty(
        name = 'Radius',
        description = 'Collision radius',
        min = 0,
        default = 0,
        override={'LIBRARY_OVERRIDABLE'},
        update=lambda s, c: update_prop(s, c, 'wiggle_radius')
    )
    bpy.types.PoseBone.wiggle_friction = bpy.props.FloatProperty(
        name = 'Friction',
        description = 'Friction when colliding',
        min = 0,
        default = 0.5,
        soft_max = 1,
        override={'LIBRARY_OVERRIDABLE'},
        update=lambda s, c: update_prop(s, c, 'wiggle_friction')
    )
    bpy.types.PoseBone.wiggle_bounce = bpy.props.FloatProperty(
        name = 'Bounce',
        description = 'Bounciness when colliding',
        min = 0,
        default = 0.5,
        soft_max = 1,
        override={'LIBRARY_OVERRIDABLE'},
        update=lambda s, c: update_prop(s, c, 'wiggle_bounce')
    )
    bpy.types.PoseBone.wiggle_sticky = bpy.props.FloatProperty(
        name = 'Sticky',
        description = 'Margin beyond radius to keep item stuck to surface',
        min = 0,
        default = 0,
        soft_max = 1,
        override={'LIBRARY_OVERRIDABLE'},
        update=lambda s, c: update_prop(s, c, 'wiggle_sticky')
    )
    
    #internal variables
    bpy.utils.register_class(WiggleItem)
    bpy.utils.register_class(WiggleScene)
    bpy.types.Scene.wiggle = bpy.props.PointerProperty(type=WiggleScene, override={'LIBRARY_OVERRIDABLE'})
    
    bpy.utils.register_class(WiggleReset)
    bpy.utils.register_class(WiggleCopy)
    bpy.utils.register_class(WiggleSelect)
    bpy.utils.register_class(WiggleBake)
    bpy.utils.register_class(WIGGLE_PT_Settings)
    bpy.utils.register_class(WIGGLE_PT_Utilities)
    bpy.utils.register_class(WIGGLE_PT_Bake)
    
    bpy.app.handlers.frame_change_pre.clear()
    bpy.app.handlers.frame_change_post.clear()
    bpy.app.handlers.render_pre.clear()
    bpy.app.handlers.render_post.clear()
    
    bpy.app.handlers.frame_change_pre.append(wiggle_pre)
    bpy.app.handlers.frame_change_post.append(wiggle_post)

def unregister():
    bpy.utils.unregister_class(WiggleItem)
    bpy.utils.unregister_class(WiggleScene)
    bpy.utils.unregister_class(WiggleReset)
    bpy.utils.unregister_class(WiggleCopy)
    bpy.utils.unregister_class(WiggleSelect)
    bpy.utils.unregister_class(WiggleBake)
    bpy.utils.unregister_class(WIGGLE_PT_Settings)
    bpy.utils.unregister_class(WIGGLE_PT_Utilities)
    bpy.utils.unregister_class(WIGGLE_PT_Bake)
    
    bpy.app.handlers.frame_change_pre.remove(wiggle_pre)
    bpy.app.handlers.frame_change_post.remove(wiggle_post)
    
if __name__ == "__main__":
    register()
