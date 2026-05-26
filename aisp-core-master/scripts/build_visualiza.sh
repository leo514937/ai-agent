#!/usr/bin/env bash

# 逻辑图可视化脚本

# 获取执行参数
map_name='zagMap'
pkg_path=$(cd "$(dirname "$0")";pwd)"/../"
config_path=''
out_dir=''
cur_sec=`date '+%s'`

dot_name=''

while [ $# -gt 0 ];
do
   case $1 in
   --dotName) dot_name=$2
      shift
      ;;
   esac
   shift
done

if [ -z "$dot_name" ]; then
    echo 'dotName is null!'
    exit 1
fi

dot_path="./"$dot_name".dot"
html_path="./"$dot_name".html"
png_path="./"$dot_name".png"

# 安装 graphviz
#if [ "$(uname)" = "Darwin" ]; then
#  brew install graphviz
#else
#  apt-get install graphviz
#fi

# 输出 html
dot -Tcmapx -o "$html_path" "$dot_path"
# 输出 png
dot -Tpng -o "$png_path" "$dot_path"
# 装饰 html
echo -e "<meta http-equiv=\"Content-Type\" content=\"text/html; charset=utf-8\" /><div style=\"text-align:center\">"$(cat $html_path) > $html_path
echo "<img src=\"$png_path\" usemap=\"#$map_name\"/></div><br/><br/>" >> $html_path

# 删除临时文件
rm "$dot_path"

echo 'run html output: '$html_path
echo 'run png output: '$png_path