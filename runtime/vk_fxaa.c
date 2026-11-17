// FXAA on the scene (MRPG_FXAA, live; default on). Super Mario RPG has no anti-aliasing of its own: it renders its 3D
// scene into a B10G11R11 image of the game's resolution with a depth attachment, copies that into the window image and
// draws the HUD there (on the pause menu's Map page it draws the menu into the scene image itself, after a pass that
// copies the scene elsewhere). So the scene is complete at the first pass after the scene passes that targets another
// image; there, before that pass begins, runtime/shaders/fxaa.comp smooths it in place: the scene goes into a copy,
// the shader reads the copy and writes the scene. The HUD and the menus, drawn later, stay sharp.
// - A scene pass: one colour target in B10G11R11, at least 640 wide, with a depth attachment.
// - Once per frame and image: later passes that draw into the scene again (the menu on the Map page) are not smoothed.
// - The scene image needs STORAGE usage; vk_texture.c create_tex gives it to such targets when FXAA is on at start
//   (vk_fxaa_wanted). An image without it is left alone.
// The sequential replay only: a chunked replay (MRPG_REPLAY_WORKERS) skips it.
#include "vk.h"

#include <string.h>

#include "cfg.h"
#include "fxaa_spv.h"
#include "host.h"
#include "vk_exec.h"

static struct {
    int tried, ok, logged;
    PFN_vkCmdPushDescriptorSetKHR push;
    VkDescriptorSetLayout dsl;
    VkPipelineLayout layout;
    VkPipeline pipe;
    VkSampler sampler;
    VkExecTarget scene;            // the scene image being rendered, valid while dirty
    int dirty;
    VkImage done;                  // the image smoothed in frame done_frame
    uint64_t done_frame;
    VkImage tmp;                   // the copy the shader reads
    VmaAllocation tmp_alloc;
    VkImageView tmp_view;
    uint32_t tmp_w, tmp_h;
    int tmp_fresh;                 // layout still UNDEFINED
} F;

int vk_fxaa_wanted(void) {
    static int w = -1;
    if (w < 0) w = cfg_bool("MRPG_FXAA");
    return w;
}

static int init(VkCtx *c) {
    F.tried = 1;
    F.push = (PFN_vkCmdPushDescriptorSetKHR)vkGetDeviceProcAddr(c->device, "vkCmdPushDescriptorSetKHR");
    VkDescriptorSetLayoutBinding b[2] = {
        {.binding = 0, .descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, .descriptorCount = 1,
         .stageFlags = VK_SHADER_STAGE_COMPUTE_BIT},
        {.binding = 1, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, .descriptorCount = 1,
         .stageFlags = VK_SHADER_STAGE_COMPUTE_BIT}};
    VkDescriptorSetLayoutCreateInfo dci = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,
                                           .flags = VK_DESCRIPTOR_SET_LAYOUT_CREATE_PUSH_DESCRIPTOR_BIT_KHR,
                                           .bindingCount = 2, .pBindings = b};
    VkPushConstantRange pr = {VK_SHADER_STAGE_COMPUTE_BIT, 0, 32};
    VkPipelineLayoutCreateInfo li = {.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, .setLayoutCount = 1,
                                     .pSetLayouts = &F.dsl, .pushConstantRangeCount = 1, .pPushConstantRanges = &pr};
    VkSamplerCreateInfo si = {.sType = VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO, .magFilter = VK_FILTER_LINEAR,
                              .minFilter = VK_FILTER_LINEAR, .addressModeU = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,
                              .addressModeV = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,
                              .addressModeW = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE, .maxLod = 0};
    VkShaderModuleCreateInfo mi = {.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = sizeof fxaa_spv,
                                   .pCode = fxaa_spv};
    VkShaderModule m = VK_NULL_HANDLE;
    if (!F.push || vkCreateDescriptorSetLayout(c->device, &dci, NULL, &F.dsl) != VK_SUCCESS ||
        vkCreatePipelineLayout(c->device, &li, NULL, &F.layout) != VK_SUCCESS ||
        vkCreateSampler(c->device, &si, NULL, &F.sampler) != VK_SUCCESS ||
        vkCreateShaderModule(c->device, &mi, NULL, &m) != VK_SUCCESS) {
        rt_log("vk: FXAA off: its pipeline could not be created");
        return 0;
    }
    VkComputePipelineCreateInfo ci = {.sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,
                                      .stage = {.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,
                                                .stage = VK_SHADER_STAGE_COMPUTE_BIT, .module = m, .pName = "main"},
                                      .layout = F.layout};
    VkResult r = vkCreateComputePipelines(c->device, VK_NULL_HANDLE, 1, &ci, NULL, &F.pipe);
    vkDestroyShaderModule(c->device, m, NULL);
    if (r != VK_SUCCESS) {
        rt_log("vk: FXAA off: its pipeline could not be created");
        return 0;
    }
    return F.ok = 1;
}

static void tmp_free(VkCtx *c) {
    if (F.tmp_view) vkDestroyImageView(c->device, F.tmp_view, NULL);
    if (F.tmp) vmaDestroyImage(c->vma, F.tmp, F.tmp_alloc);
    F.tmp = VK_NULL_HANDLE, F.tmp_view = VK_NULL_HANDLE, F.tmp_w = F.tmp_h = 0;
}

// The copy at w x h; another size waits for the device first (earlier submissions may still read the old one).
static int tmp_ensure(VkCtx *c, uint32_t w, uint32_t h) {
    if (F.tmp && F.tmp_w == w && F.tmp_h == h) return 1;
    if (F.tmp) {
        vk_queue_lock();
        vkDeviceWaitIdle(c->device);
        vk_queue_unlock();
        tmp_free(c);
    }
    VkImageCreateInfo ii = {.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO, .imageType = VK_IMAGE_TYPE_2D,
                            .format = VK_FORMAT_B10G11R11_UFLOAT_PACK32, .extent = {w, h, 1}, .mipLevels = 1,
                            .arrayLayers = 1, .samples = VK_SAMPLE_COUNT_1_BIT, .tiling = VK_IMAGE_TILING_OPTIMAL,
                            .usage = VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT};
    VmaAllocationCreateInfo ai = {.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE};
    if (vmaCreateImage(c->vma, &ii, &ai, &F.tmp, &F.tmp_alloc, NULL) != VK_SUCCESS) {
        F.tmp = VK_NULL_HANDLE;
        return 0;
    }
    VkImageViewCreateInfo vi = {.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO, .image = F.tmp,
                                .viewType = VK_IMAGE_VIEW_TYPE_2D, .format = VK_FORMAT_B10G11R11_UFLOAT_PACK32,
                                .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1}};
    if (vkCreateImageView(c->device, &vi, NULL, &F.tmp_view) != VK_SUCCESS) {
        F.tmp_view = VK_NULL_HANDLE;
        tmp_free(c);
        return 0;
    }
    F.tmp_w = w, F.tmp_h = h, F.tmp_fresh = 1;
    return 1;
}

static void mem_barrier(VkCommandBuffer cb, VkPipelineStageFlags2 ss, VkAccessFlags2 sa, VkPipelineStageFlags2 ds,
                        VkAccessFlags2 da) {
    VkMemoryBarrier2 mb = {.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER_2, .srcStageMask = ss, .srcAccessMask = sa,
                           .dstStageMask = ds, .dstAccessMask = da};
    VkDependencyInfo d = {.sType = VK_STRUCTURE_TYPE_DEPENDENCY_INFO, .memoryBarrierCount = 1, .pMemoryBarriers = &mb};
    vkCmdPipelineBarrier2(cb, &d);
}

static void run(VkExec *ex, const VkExecTarget *s) {
    VkCtx *c = vk_ctx();
    if (!F.tried) init(c);
    if (!F.ok || !s->img || !(s->img->usage & VK_IMAGE_USAGE_STORAGE_BIT) || !tmp_ensure(c, s->width, s->height)) return;
    VkImageView out = vk_exec_target_view(s->img, VK_FORMAT_B10G11R11_UFLOAT_PACK32, VK_IMAGE_VIEW_TYPE_2D,
                                          VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1, 0);
    if (!out) return;
    vk_exec_barrier(ex);   // the scene passes' writes are done, and the scene is in GENERAL (vk_exec.c barrier_to)
    VkCommandBuffer cb = ex->cb;
    if (F.tmp_fresh) {
        VkImageMemoryBarrier2 b = {.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER_2,
                                   .srcStageMask = VK_PIPELINE_STAGE_2_NONE, .dstStageMask = VK_PIPELINE_STAGE_2_COPY_BIT,
                                   .dstAccessMask = VK_ACCESS_2_TRANSFER_WRITE_BIT, .oldLayout = VK_IMAGE_LAYOUT_UNDEFINED,
                                   .newLayout = VK_IMAGE_LAYOUT_GENERAL, .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                                   .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .image = F.tmp,
                                   .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1}};
        VkDependencyInfo d = {.sType = VK_STRUCTURE_TYPE_DEPENDENCY_INFO, .imageMemoryBarrierCount = 1,
                              .pImageMemoryBarriers = &b};
        vkCmdPipelineBarrier2(cb, &d);
        F.tmp_fresh = 0;
    }
    VkImageCopy cp = {.srcSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1},
                      .dstSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, .extent = {s->width, s->height, 1}};
    vkCmdCopyImage(cb, s->image, VK_IMAGE_LAYOUT_GENERAL, F.tmp, VK_IMAGE_LAYOUT_GENERAL, 1, &cp);
    mem_barrier(cb, VK_PIPELINE_STAGE_2_COPY_BIT, VK_ACCESS_2_TRANSFER_WRITE_BIT | VK_ACCESS_2_TRANSFER_READ_BIT,
                VK_PIPELINE_STAGE_2_COMPUTE_SHADER_BIT, VK_ACCESS_2_SHADER_SAMPLED_READ_BIT | VK_ACCESS_2_SHADER_STORAGE_WRITE_BIT);
    VkDescriptorImageInfo ii = {F.sampler, F.tmp_view, VK_IMAGE_LAYOUT_GENERAL}, oi = {VK_NULL_HANDLE, out, VK_IMAGE_LAYOUT_GENERAL};
    VkWriteDescriptorSet w[2] = {
        {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = 0, .descriptorCount = 1,
         .descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, .pImageInfo = &ii},
        {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = 1, .descriptorCount = 1,
         .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, .pImageInfo = &oi}};
    struct { float pc[4]; int32_t size[4]; } pc = {{1.0f / (float)s->width, 1.0f / (float)s->height, 0.75f, 0.125f},
                                                    {(int32_t)s->width, (int32_t)s->height, 0, 0}};
    vkCmdBindPipeline(cb, VK_PIPELINE_BIND_POINT_COMPUTE, F.pipe);
    rec_push(F.push, cb, VK_PIPELINE_BIND_POINT_COMPUTE, F.layout, 0, 2, w);
    vkCmdPushConstants(cb, F.layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof pc, &pc);
    vkCmdDispatch(cb, (s->width + 7) / 8, (s->height + 7) / 8, 1);
    mem_barrier(cb, VK_PIPELINE_STAGE_2_COMPUTE_SHADER_BIT, VK_ACCESS_2_SHADER_STORAGE_WRITE_BIT | VK_ACCESS_2_SHADER_SAMPLED_READ_BIT,
                VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT, VK_ACCESS_2_MEMORY_READ_BIT | VK_ACCESS_2_MEMORY_WRITE_BIT);
    ex->recorded += 7;
    vk_exec_draw_new_cb(ex);   // the game's bound compute pipeline and descriptors were replaced: bind them again
    if (!F.logged) F.logged = 1, rt_log("vk: FXAA on a %ux%u scene", s->width, s->height);
}

static int is_scene_pass(const VkExec *ex) {
    const VkExecTarget *t = &ex->color[0];
    return !ex->pass_noatt && ex->pass_ncolor == 1 && t->image && !t->level && t->format == VK_FORMAT_B10G11R11_UFLOAT_PACK32 &&
           t->width >= 640 && ex->depth.image;
}

void vk_fxaa_pass_begin(VkExec *ex) {
    if (ex->chunked || !vk_fxaa_wanted()) return;
    uint64_t frame = __atomic_load_n(&gfx_counters.frames, __ATOMIC_RELAXED);
    if (is_scene_pass(ex)) {
        if (!(F.done == ex->color[0].image && F.done_frame == frame)) F.scene = ex->color[0], F.dirty = 1;
        return;
    }
    if (!F.dirty || ex->color[0].image == F.scene.image) return;
    F.dirty = 0;
    if (!cfg_bool("MRPG_FXAA")) return;   // the menu switched it off
    F.done = F.scene.image, F.done_frame = frame;
    run(ex, &F.scene);
}

void vk_fxaa_image_gone(VkImage image) {   // a texture image went away (vk_exec_draw.c)
    if (F.scene.image == image) F.dirty = 0, F.scene.image = VK_NULL_HANDLE;
    if (F.done == image) F.done = VK_NULL_HANDLE;
}

void vk_fxaa_release(void) {
    VkCtx *c = vk_ctx();
    if (!c || !F.tried) return;
    tmp_free(c);
    if (F.pipe) vkDestroyPipeline(c->device, F.pipe, NULL);
    if (F.sampler) vkDestroySampler(c->device, F.sampler, NULL);
    if (F.layout) vkDestroyPipelineLayout(c->device, F.layout, NULL);
    if (F.dsl) vkDestroyDescriptorSetLayout(c->device, F.dsl, NULL);
    memset(&F, 0, sizeof F);
}
