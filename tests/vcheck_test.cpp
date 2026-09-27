#define CL_TARGET_OPENCL_VERSION 120
#include <boost/compute/core.hpp>
#include <boost/compute/system.hpp>
#include <boost/compute/utility/dim.hpp>
#include <cmath>
#include <iostream>
#include <vector>
#include "../src/EEDI3CL_kernels.cl"

int main() {
  try {
    namespace cl = boost::compute;
    const auto device = cl::system::devices().at(0);
    cl::context context(device);
    cl::command_queue queue(context, device);
    const std::string text = std::string("constant sampler_t sampler = CLK_NORMALIZED_COORDS_FALSE | CLK_ADDRESS_CLAMP_TO_EDGE | CLK_FILTER_NEAREST;\n") + interpolation_kernels_source;
    auto program = cl::program::build_with_source(text, context);
    auto kernel = program.create_kernel("vCheck_float");
    constexpr int w=8,h=8;
    std::vector<float> values(w*h), fallback(w*h,0.4f), result(w*h);
    std::vector<int> directions(w*h,1);
    for(int y=0;y<h;++y) for(int x=0;x<w;++x) values[y*w+x]=(y%2)?0.3f:0.1f;
    cl::image_format format(CL_R,CL_FLOAT);
    cl::image2d src(context,w+24,h+8,format,CL_MEM_READ_ONLY);
    cl::image2d input(context,w,h,format,CL_MEM_READ_ONLY);
    cl::image2d output(context,w,h,format,CL_MEM_WRITE_ONLY);
    cl::buffer dmap(context,directions.size()*sizeof(int),CL_MEM_READ_ONLY|CL_MEM_COPY_HOST_PTR,directions.data());
    cl::buffer sclip(context,fallback.size()*sizeof(float),CL_MEM_READ_ONLY|CL_MEM_COPY_HOST_PTR,fallback.data());
    queue.enqueue_write_image(input,cl::dim(0,0),cl::dim(w,h),values.data(),w*sizeof(float));
    const size_t global[]{w,h/2};
    for(int peak : {0,1}) {
      // mdiff0 = 0.2, so its threshold weight is 2 and must saturate at 1
      // for chroma as well as luma. The pixel range is not the weight range.
      kernel.set_args(src,input,output,dmap,sclip,1,w,h,int(w*sizeof(float)),0,2,4.f,10.f,10.f,0.25f,peak,4);
      queue.enqueue_nd_range_kernel(kernel,2,nullptr,global,nullptr);
      queue.enqueue_read_image(output,cl::dim(0,0),cl::dim(w,h),result.data(),w*sizeof(float));
      if(std::abs(result[2*w+3]-0.4f)>1.e-6f) {
        std::cerr << "vCheck blend weight: peak="<<peak<<", expected 0.4, got "<<result[2*w+3]<<'\n';
        return 1;
      }
    }
    std::cout<<"Float luma/chroma vCheck blend weights passed\n";
  } catch(const std::exception& e) { std::cerr<<e.what()<<'\n'; return 1; }
}
